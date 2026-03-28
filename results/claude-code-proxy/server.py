#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.client
import json
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
DEFAULT_HEALTH_PATHS = {"/", "/health", "/ready", "/status"}


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _redact_value(name: str, value: str, *, log_secrets: bool) -> str:
    if log_secrets:
        return value
    if any(token in name.lower() for token in SENSITIVE_HEADER_TOKENS):
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
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(redacted_items, doseq=True), parsed.fragment)
    )


def _join_upstream_path(base_path: str, request_path: str) -> str:
    normalized_base = base_path.rstrip("/")
    normalized_request = request_path or "/"
    if not normalized_request.startswith("/"):
        normalized_request = f"/{normalized_request}"

    if normalized_base and (
        normalized_request == normalized_base or normalized_request.startswith(f"{normalized_base}/")
    ):
        return normalized_request

    joined = f"{normalized_base}{normalized_request}"
    return joined or "/"


def _is_local_health_path(raw_path: str) -> bool:
    return urlsplit(raw_path).path in DEFAULT_HEALTH_PATHS


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClaudeCodeProxy/0.2"

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            return self.rfile.read(int(length))
        except Exception:
            return b""

    def _handle_proxy(self) -> None:
        request_body = self._read_body()
        self.close_connection = True
        if _is_local_health_path(self.path):
            response_bytes = json.dumps(
                {
                    "ok": True,
                    "service": "claude-code-proxy",
                    "listener": self.server.listener_name,
                    "upstream_base_url": self.server.upstream_base_url,
                }
            ).encode("utf-8")
            self._send_local_response(200, response_bytes)
            return

        exchange_id = self.server.next_exchange_id()
        started_at = time.time()
        request_path = _redact_query(self.path, log_secrets=self.server.log_secrets)

        request_stem = self.server.make_stem(exchange_id, started_at, "request", self.command, request_path)
        request_body_path = self.server.bodies_dir / f"{request_stem}.bin"
        request_body_path.write_bytes(request_body)

        self.server.append_request(
            {
                "id": exchange_id,
                "ts": started_at,
                "listener": self.server.listener_name,
                "method": self.command,
                "path": request_path,
                "headers": {
                    key: _redact_value(key, value, log_secrets=self.server.log_secrets)
                    for key, value in self.headers.items()
                },
                "body_path": str(request_body_path),
                "body_size": len(request_body),
                "upstream_base_url": self.server.upstream_base_url,
            }
        )

        upstream_response = None
        response_body_path = None
        target_url = None

        try:
            connection = self.server.make_connection()
            upstream_target = self.server.build_upstream_target(self.path)
            forwarded_headers = self.server.build_upstream_headers(self.headers, len(request_body))
            target_url = self.server.build_logged_target_url(upstream_target)

            connection.request(self.command, upstream_target, body=request_body, headers=forwarded_headers)
            upstream_response = connection.getresponse()

            response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
            response_body_path = self.server.bodies_dir / f"{response_stem}.bin"

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
                    if self.command != "HEAD":
                        self.wfile.write(chunk)
                if self.command != "HEAD":
                    self.wfile.flush()

            self.server.append_response(
                {
                    "id": exchange_id,
                    "ts": time.time(),
                    "duration_ms": round((time.time() - started_at) * 1000, 3),
                    "listener": self.server.listener_name,
                    "method": self.command,
                    "path": request_path,
                    "target_url": target_url,
                    "status": upstream_response.status,
                    "reason": upstream_response.reason,
                    "headers": response_headers,
                    "body_path": str(response_body_path),
                    "body_size": body_size,
                }
            )
        except Exception as exc:
            error_payload = json.dumps(
                {
                    "ok": False,
                    "error": "proxy_error",
                    "detail": str(exc),
                }
            ).encode("utf-8")
            self._send_local_response(502, error_payload)

            if response_body_path is None:
                response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
                response_body_path = self.server.bodies_dir / f"{response_stem}.bin"
            response_body_path.write_bytes(error_payload)

            self.server.append_response(
                {
                    "id": exchange_id,
                    "ts": time.time(),
                    "duration_ms": round((time.time() - started_at) * 1000, 3),
                    "listener": self.server.listener_name,
                    "method": self.command,
                    "path": request_path,
                    "target_url": target_url,
                    "status": 502,
                    "reason": "Bad Gateway",
                    "headers": {
                        "Content-Type": "application/json",
                        "Content-Length": str(len(error_payload)),
                    },
                    "body_path": str(response_body_path),
                    "body_size": len(error_payload),
                    "error": str(exc),
                }
            )
        finally:
            if upstream_response is not None:
                upstream_response.close()

    def _send_local_response(self, status: int, response_bytes: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response_bytes)
            self.wfile.flush()

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
        listener_name: str,
        upstream: SplitResult,
        upstream_base_url: str,
        request_timeout: int,
        log_secrets: bool,
        preserve_accept_encoding: bool,
        request_log_path: Path,
        response_log_path: Path,
        bodies_dir: Path,
    ):
        super().__init__(server_address, handler_cls)
        self.listener_name = listener_name
        self.upstream = upstream
        self.upstream_base_url = upstream_base_url
        self.request_timeout = request_timeout
        self.log_secrets = log_secrets
        self.preserve_accept_encoding = preserve_accept_encoding
        self.request_log_path = request_log_path
        self.response_log_path = response_log_path
        self.bodies_dir = bodies_dir
        self._exchange_lock = threading.Lock()
        self._exchange_counter = 0

    def next_exchange_id(self) -> int:
        with self._exchange_lock:
            self._exchange_counter += 1
            return self._exchange_counter

    def append_request(self, entry: dict) -> None:
        with self._exchange_lock:
            with self.request_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    def append_response(self, entry: dict) -> None:
        with self._exchange_lock:
            with self.response_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    def make_stem(self, exchange_id: int, started_at: float, prefix: str, method: str, path: str) -> str:
        return f"{exchange_id:04d}-{int(started_at)}-{prefix}-{_safe_name(method)}-{_safe_name(path)[:80]}"

    def make_connection(self) -> http.client.HTTPConnection:
        if self.upstream.scheme == "https":
            context = ssl.create_default_context()
            return http.client.HTTPSConnection(
                self.upstream.hostname,
                self.upstream.port or 443,
                timeout=self.request_timeout,
                context=context,
            )
        return http.client.HTTPConnection(
            self.upstream.hostname,
            self.upstream.port or 80,
            timeout=self.request_timeout,
        )

    def build_upstream_target(self, raw_path: str) -> str:
        target = urlsplit(raw_path)
        upstream_path = _join_upstream_path(self.upstream.path, target.path)
        return urlunsplit(("", "", upstream_path, target.query, target.fragment))

    def build_target_url(self, upstream_target: str) -> str:
        return urlunsplit(
            (
                self.upstream.scheme,
                self.upstream.netloc,
                urlsplit(upstream_target).path,
                urlsplit(upstream_target).query,
                urlsplit(upstream_target).fragment,
            )
        )

    def build_logged_target_url(self, upstream_target: str) -> str:
        return _redact_query(self.build_target_url(upstream_target), log_secrets=self.log_secrets)

    def build_upstream_headers(self, headers, body_length: int) -> dict[str, str]:
        forwarded = {}
        for key, value in headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower == "host":
                continue
            if lower == "content-length":
                continue
            if lower == "accept-encoding" and not self.preserve_accept_encoding:
                continue
            forwarded[key] = value
        forwarded["Host"] = self.upstream.netloc
        forwarded["Content-Length"] = str(body_length)
        if not self.preserve_accept_encoding:
            # Plain upstream bodies are easier to inspect than gzip/br payloads.
            forwarded["Accept-Encoding"] = "identity"
        return forwarded


def _serve_http(server: ProxyServer) -> None:
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture Claude Code traffic by reverse-proxying requests sent through ANTHROPIC_BASE_URL."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    parser.add_argument("--https-port", type=int, default=None)
    parser.add_argument("--cert", default=None, help="PEM certificate for the HTTPS listener.")
    parser.add_argument("--key", default=None, help="PEM private key for the HTTPS listener.")
    parser.add_argument("--upstream", default="https://api.anthropic.com")
    parser.add_argument("--request-timeout", type=int, default=120)
    parser.add_argument("--log-secrets", action="store_true")
    parser.add_argument(
        "--preserve-accept-encoding",
        action="store_true",
        help="Forward the client Accept-Encoding header instead of forcing identity upstream.",
    )
    parser.add_argument("--request-log", default="../targets/claude-code/proxy-requests.jsonl")
    parser.add_argument("--response-log", default="../targets/claude-code/proxy-responses.jsonl")
    parser.add_argument("--bodies-dir", default="../targets/claude-code/proxy-bodies")
    args = parser.parse_args()

    upstream = urlsplit(args.upstream)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname:
        raise SystemExit(f"Unsupported upstream URL: {args.upstream}")

    if args.https_port is not None and (not args.cert or not args.key):
        raise SystemExit("--https-port requires both --cert and --key")

    root = Path(__file__).resolve().parent
    request_log_path = (root / args.request_log).resolve()
    response_log_path = (root / args.response_log).resolve()
    bodies_dir = (root / args.bodies_dir).resolve()
    request_log_path.parent.mkdir(parents=True, exist_ok=True)
    response_log_path.parent.mkdir(parents=True, exist_ok=True)
    bodies_dir.mkdir(parents=True, exist_ok=True)

    http_server = ProxyServer(
        (args.host, args.port),
        ProxyHandler,
        listener_name="http",
        upstream=upstream,
        upstream_base_url=args.upstream,
        request_timeout=args.request_timeout,
        log_secrets=args.log_secrets,
        preserve_accept_encoding=args.preserve_accept_encoding,
        request_log_path=request_log_path,
        response_log_path=response_log_path,
        bodies_dir=bodies_dir,
    )

    threads: list[threading.Thread] = []
    https_server: Optional[ProxyServer] = None
    if args.https_port is not None:
        https_server = ProxyServer(
            (args.host, args.https_port),
            ProxyHandler,
            listener_name="https",
            upstream=upstream,
            upstream_base_url=args.upstream,
            request_timeout=args.request_timeout,
            log_secrets=args.log_secrets,
            preserve_accept_encoding=args.preserve_accept_encoding,
            request_log_path=request_log_path,
            response_log_path=response_log_path,
            bodies_dir=bodies_dir,
        )
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(certfile=args.cert, keyfile=args.key)
        https_server.socket = ssl_context.wrap_socket(https_server.socket, server_side=True)
        thread = threading.Thread(target=_serve_http, args=(https_server,), daemon=True)
        thread.start()
        threads.append(thread)

    print(
        json.dumps(
            {
                "service": "claude-code-proxy",
                "http": f"http://{args.host}:{args.port}",
                "https": f"https://{args.host}:{args.https_port}" if args.https_port is not None else None,
                "upstream": args.upstream,
                "request_log": str(request_log_path),
                "response_log": str(response_log_path),
                "bodies_dir": str(bodies_dir),
            }
        ),
        flush=True,
    )

    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        http_server.server_close()
        if https_server is not None:
            https_server.server_close()
        for thread in threads:
            thread.join(timeout=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
