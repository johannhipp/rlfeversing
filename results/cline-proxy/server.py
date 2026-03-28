#!/usr/bin/env python3

import argparse
import http.client
import json
import os
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

SENSITIVE_HEADER_TOKENS = ("authorization", "api-key", "token", "secret", "cookie")
SENSITIVE_QUERY_TOKENS = ("key", "token", "secret", "sig", "signature")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _redact_value(name: str, value: str, *, log_secrets: bool) -> str:
    if log_secrets:
        return value
    lower_name = name.lower()
    if any(token in lower_name for token in SENSITIVE_HEADER_TOKENS):
        return "<redacted>"
    return value


def _redact_query(raw_path: str, *, log_secrets: bool) -> str:
    if log_secrets:
        return raw_path

    parsed = urlsplit(raw_path)
    if not parsed.query:
        return raw_path

    redacted_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if any(token in key.lower() for token in SENSITIVE_QUERY_TOKENS):
            redacted_items.append((key, "<redacted>"))
        else:
            redacted_items.append((key, value))

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(redacted_items, doseq=True),
            parsed.fragment,
        )
    )


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClineProxy/0.1"

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            return self.rfile.read(int(length))
        except Exception:
            return b""

    def _handle_proxy(self) -> None:
        body = self._read_body()
        self.close_connection = True

        exchange_id = self.server.next_exchange_id()
        started_at = time.time()
        request_path = _redact_query(self.path, log_secrets=self.server.log_secrets)

        request_stem = self.server.make_stem(exchange_id, started_at, "request", self.command, request_path)
        request_body_path = self.server.requests_dir / f"{request_stem}.bin"
        request_body_path.write_bytes(body)

        exchange = {
            "id": exchange_id,
            "started_at": started_at,
            "request": {
                "method": self.command,
                "path": request_path,
                "headers": {
                    key: _redact_value(key, value, log_secrets=self.server.log_secrets)
                    for key, value in self.headers.items()
                },
                "body_path": str(request_body_path),
                "body_size": len(body),
            },
            "upstream": {
                "base_url": self.server.upstream_base_url,
            },
        }

        if self.path.split("?", 1)[0] in self.server.health_paths:
            payload = {
                "ok": True,
                "status": "ready",
                "service": "cline-proxy",
                "upstream_base_url": self.server.upstream_base_url,
            }
            response_bytes = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_bytes)
            self.wfile.flush()

            response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
            response_body_path = self.server.responses_dir / f"{response_stem}.bin"
            response_body_path.write_bytes(response_bytes)
            exchange["response"] = {
                "status": 200,
                "reason": "OK",
                "headers": {"Content-Type": "application/json", "Content-Length": str(len(response_bytes))},
                "body_path": str(response_body_path),
                "body_size": len(response_bytes),
            }
            exchange["finished_at"] = time.time()
            exchange["duration_ms"] = round((exchange["finished_at"] - started_at) * 1000, 3)
            self.server.append_exchange(exchange)
            return

        upstream_response = None
        response_body_path = None

        try:
            connection = self.server.make_connection()
            target = self.server.build_upstream_target(self.path)
            forwarded_headers = self.server.build_upstream_headers(self.headers, len(body))

            exchange["upstream"]["target"] = target

            connection.request(self.command, target, body=body, headers=forwarded_headers)
            upstream_response = connection.getresponse()

            response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
            response_body_path = self.server.responses_dir / f"{response_stem}.bin"

            self.send_response(upstream_response.status, upstream_response.reason)
            response_headers = {}
            for key, value in upstream_response.getheaders():
                key_lower = key.lower()
                if key_lower in HOP_BY_HOP_HEADERS:
                    continue
                response_headers[key] = _redact_value(key, value, log_secrets=self.server.log_secrets)
                self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()

            body_size = 0
            with response_body_path.open("wb") as response_fh:
                while True:
                    chunk = upstream_response.read(65536)
                    if not chunk:
                        break
                    body_size += len(chunk)
                    response_fh.write(chunk)
                    self.wfile.write(chunk)
                self.wfile.flush()

            exchange["response"] = {
                "status": upstream_response.status,
                "reason": upstream_response.reason,
                "headers": response_headers,
                "body_path": str(response_body_path),
                "body_size": body_size,
            }
        except Exception as exc:
            error_payload = json.dumps(
                {
                    "ok": False,
                    "error": "proxy_error",
                    "detail": str(exc),
                }
            ).encode("utf-8")
            self.send_response(502, "Bad Gateway")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error_payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(error_payload)
            self.wfile.flush()

            if response_body_path is None:
                response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
                response_body_path = self.server.responses_dir / f"{response_stem}.bin"
            response_body_path.write_bytes(error_payload)

            exchange["response"] = {
                "status": 502,
                "reason": "Bad Gateway",
                "headers": {"Content-Type": "application/json", "Content-Length": str(len(error_payload))},
                "body_path": str(response_body_path),
                "body_size": len(error_payload),
            }
            exchange["error"] = str(exc)
        finally:
            if upstream_response is not None:
                upstream_response.close()

        exchange["finished_at"] = time.time()
        exchange["duration_ms"] = round((exchange["finished_at"] - started_at) * 1000, 3)
        self.server.append_exchange(exchange)

    def do_DELETE(self) -> None:
        self._handle_proxy()

    def do_GET(self) -> None:
        self._handle_proxy()

    def do_HEAD(self) -> None:
        self._handle_proxy()

    def do_OPTIONS(self) -> None:
        self._handle_proxy()

    def do_PATCH(self) -> None:
        self._handle_proxy()

    def do_POST(self) -> None:
        self._handle_proxy()

    def do_PUT(self) -> None:
        self._handle_proxy()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(fmt % args + "\n")


class ProxyServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[ProxyHandler],
        *,
        upstream: SplitResult,
        upstream_base_url: str,
        mount_path: str,
        timeout: float,
        log_path: Path,
        bodies_dir: Path,
        upstream_api_key_env: Optional[str],
        insecure: bool,
        log_secrets: bool,
    ):
        super().__init__(server_address, handler_cls)
        self.upstream = upstream
        self.upstream_base_url = upstream_base_url
        self.mount_path = self._normalize_prefix(mount_path)
        self.timeout = timeout
        self.log_path = log_path
        self.bodies_dir = bodies_dir
        self.requests_dir = bodies_dir / "requests"
        self.responses_dir = bodies_dir / "responses"
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_lock = threading.Lock()
        self.counter_lock = threading.Lock()
        self.counter = 0
        self.upstream_api_key_env = upstream_api_key_env
        self.insecure = insecure
        self.log_secrets = log_secrets
        self.health_paths = {"/", "/health", "/healthz", "/ready", "/status"}
        self.ssl_context = None
        if self.upstream.scheme == "https":
            self.ssl_context = ssl.create_default_context()
            if self.insecure:
                self.ssl_context.check_hostname = False
                self.ssl_context.verify_mode = ssl.CERT_NONE

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        if not prefix:
            return "/"
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        if prefix != "/" and prefix.endswith("/"):
            prefix = prefix[:-1]
        return prefix

    def next_exchange_id(self) -> int:
        with self.counter_lock:
            self.counter += 1
            return self.counter

    def make_stem(self, exchange_id: int, now: float, kind: str, method: str, path: str) -> str:
        safe_path = _safe_name(path)[:80] or "root"
        return f"{exchange_id:04d}-{int(now)}-{kind}-{_safe_name(method)}-{safe_path}"

    def build_upstream_target(self, raw_path: str) -> str:
        parsed = urlsplit(raw_path)
        incoming_path = parsed.path or "/"
        relative_path = incoming_path
        if self.mount_path != "/" and incoming_path.startswith(self.mount_path):
            relative_path = incoming_path[len(self.mount_path) :] or "/"

        base_path = self.upstream.path or ""
        if base_path.endswith("/") and relative_path.startswith("/"):
            path = base_path[:-1] + relative_path
        elif not base_path and not relative_path.startswith("/"):
            path = "/" + relative_path
        else:
            path = base_path + relative_path

        if not path.startswith("/"):
            path = "/" + path

        return urlunsplit(("", "", path, parsed.query, ""))

    def build_upstream_headers(self, headers, body_size: int) -> dict[str, str]:
        forwarded = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower in HOP_BY_HOP_HEADERS or key_lower == "host":
                continue
            if key_lower == "accept-encoding":
                continue
            forwarded[key] = value

        forwarded["Host"] = self.upstream.netloc
        forwarded["Accept-Encoding"] = "identity"
        if body_size:
            forwarded["Content-Length"] = str(body_size)
        else:
            forwarded.pop("Content-Length", None)

        if self.upstream_api_key_env:
            token = self._read_upstream_api_key()
            if token:
                forwarded["Authorization"] = f"Bearer {token}"

        return forwarded

    def _read_upstream_api_key(self) -> Optional[str]:
        value = None
        if self.upstream_api_key_env:
            value = os.environ.get(self.upstream_api_key_env)
        return value or None

    def make_connection(self):
        if self.upstream.scheme == "https":
            return http.client.HTTPSConnection(
                self.upstream.hostname,
                self.upstream.port or 443,
                timeout=self.timeout,
                context=self.ssl_context,
            )
        return http.client.HTTPConnection(
            self.upstream.hostname,
            self.upstream.port or 80,
            timeout=self.timeout,
        )

    def append_exchange(self, exchange: dict) -> None:
        with self.log_lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(exchange, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reverse proxy for capturing Cline provider traffic")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18421, type=int)
    parser.add_argument("--mount-path", default="/v1")
    parser.add_argument("--upstream-base-url", required=True)
    parser.add_argument("--upstream-api-key-env")
    parser.add_argument("--timeout", default=120.0, type=float)
    parser.add_argument("--log", default="../targets/cline/proxy-exchanges.jsonl")
    parser.add_argument("--bodies-dir", default="../targets/cline/proxy-bodies")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--log-secrets", action="store_true")
    parser.add_argument("--cert-file")
    parser.add_argument("--key-file")
    args = parser.parse_args()

    upstream = urlsplit(args.upstream_base_url)
    if upstream.scheme not in {"http", "https"}:
        raise SystemExit("--upstream-base-url must start with http:// or https://")
    if not upstream.netloc:
        raise SystemExit("--upstream-base-url must include a host")

    root = Path(__file__).resolve().parent
    log_path = (root / args.log).resolve()
    bodies_dir = (root / args.bodies_dir).resolve()

    server = ProxyServer(
        (args.host, args.port),
        ProxyHandler,
        upstream=upstream,
        upstream_base_url=args.upstream_base_url,
        mount_path=args.mount_path,
        timeout=args.timeout,
        log_path=log_path,
        bodies_dir=bodies_dir,
        upstream_api_key_env=args.upstream_api_key_env,
        insecure=args.insecure,
        log_secrets=args.log_secrets,
    )

    scheme = "http"
    if args.cert_file and args.key_file:
        scheme = "https"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert_file, args.key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)

    print(
        json.dumps(
            {
                "listening": f"{scheme}://{args.host}:{args.port}{server.mount_path}",
                "upstream_base_url": args.upstream_base_url,
                "log_path": str(log_path),
                "bodies_dir": str(bodies_dir),
            }
        ),
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
