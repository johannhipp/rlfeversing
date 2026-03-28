#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import ssl
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
}

TEXTUAL_CONTENT_TYPES = {
    "application/json",
    "application/problem+json",
    "application/x-ndjson",
    "application/xml",
    "text/event-stream",
}

JSON_SUMMARY_BODY_LIMIT = 1_000_000


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _sanitize_headers(headers: list[tuple[str, str]]) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in headers:
        sanitized[key] = "<redacted>" if key.lower() in SENSITIVE_HEADERS else value
    return sanitized


def _is_textual_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False

    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type.startswith("text/") or media_type in TEXTUAL_CONTENT_TYPES or media_type.endswith("+json")


def _truncate_text(value: str, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def _extract_json_summary(body: bytes, headers: dict[str, str]) -> dict[str, object] | None:
    content_type = headers.get("Content-Type") or headers.get("content-type")
    if not body or not _is_textual_content_type(content_type) or len(body) > JSON_SUMMARY_BODY_LIMIT:
        return None

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if isinstance(payload, list):
        return {
            "root_type": "list",
            "items": len(payload),
        }

    if not isinstance(payload, dict):
        return {
            "root_type": type(payload).__name__,
        }

    summary: dict[str, object] = {
        "root_type": "object",
        "top_level_keys": sorted(payload.keys())[:12],
    }

    for key in ("id", "model", "object"):
        value = payload.get(key)
        if isinstance(value, str):
            summary[key] = value

    stream = payload.get("stream")
    if isinstance(stream, bool):
        summary["stream"] = stream

    if isinstance(payload.get("messages"), list):
        summary["messages_count"] = len(payload["messages"])
    if isinstance(payload.get("tools"), list):
        summary["tools_count"] = len(payload["tools"])
    if isinstance(payload.get("choices"), list):
        summary["choices_count"] = len(payload["choices"])
    if isinstance(payload.get("output"), list):
        summary["output_count"] = len(payload["output"])

    input_value = payload.get("input")
    if isinstance(input_value, list):
        summary["input_count"] = len(input_value)
    elif isinstance(input_value, str):
        summary["input_chars"] = len(input_value)

    usage = payload.get("usage")
    if isinstance(usage, dict):
        usage_summary = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                usage_summary[key] = value
        if usage_summary:
            summary["usage"] = usage_summary

    error = payload.get("error")
    if isinstance(error, dict):
        error_summary = {}
        error_type = error.get("type")
        if isinstance(error_type, str):
            error_summary["type"] = error_type
        error_code = error.get("code")
        if isinstance(error_code, str):
            error_summary["code"] = error_code
        error_message = error.get("message")
        if isinstance(error_message, str):
            error_summary["message_preview"] = _truncate_text(error_message)
        if error_summary:
            summary["error"] = error_summary

    return summary


def _build_body_metadata(body: bytes, headers: dict[str, str]) -> dict[str, object]:
    metadata: dict[str, object] = {
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    content_type = headers.get("Content-Type") or headers.get("content-type")
    if content_type:
        metadata["content_type"] = content_type

    if body and _is_textual_content_type(content_type):
        preview = body.decode("utf-8", errors="replace")
        if len(preview) > 2000:
            metadata["text_preview"] = preview[:2000]
            metadata["text_truncated"] = True
        else:
            metadata["text_preview"] = preview

    json_summary = _extract_json_summary(body, headers)
    if json_summary is not None:
        metadata["json_summary"] = json_summary

    return metadata


def _build_logged_body(
    body: bytes,
    headers: dict[str, str],
    *,
    body_path: str,
    inline_bodies: bool,
) -> dict[str, object]:
    entry = {
        "body_path": body_path,
        **_build_body_metadata(body, headers),
    }
    if inline_bodies:
        entry["body_b64"] = base64.b64encode(body).decode("ascii")
    return entry


def _build_forward_headers(headers: list[tuple[str, str]], host: str, *, preserve_accept_encoding: bool) -> dict[str, str]:
    forwarded = {
        key: value
        for key, value in headers
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
    }
    forwarded["Host"] = host
    forwarded["Connection"] = "close"
    if not preserve_accept_encoding:
        # Force a readable upstream response for capture logs instead of compressed blobs.
        forwarded["Accept-Encoding"] = "identity"
    return forwarded


def _join_upstream_path(base_path: str, request_path: str) -> str:
    normalized_base = base_path.rstrip("/")
    normalized_request = request_path or "/"
    if not normalized_request.startswith("/"):
        normalized_request = f"/{normalized_request}"

    # Aider sends the configured base path as part of the request path.
    if normalized_base and (
        normalized_request == normalized_base or normalized_request.startswith(f"{normalized_base}/")
    ):
        return normalized_request

    joined = f"{normalized_base}{normalized_request}"
    return joined or "/"


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AiderProxy/0.1"

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        return self.rfile.read(int(length))

    def _next_stem(self) -> str:
        now = time.time()
        idx = self.server.next_id()
        return f"{idx:04d}-{int(now)}-{_safe_name(self.command)}-{_safe_name(self.path)[:80]}"

    def _write_blob(self, stem: str, suffix: str, data: bytes) -> str:
        path = self.server.bodies_dir / f"{stem}-{suffix}.bin"
        path.write_bytes(data)
        return str(path)

    def _log_json(self, entry: dict[str, object]) -> None:
        with self.server.log_lock:
            with self.server.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    def _health_response(self) -> None:
        payload = json.dumps(
            {
                "ok": True,
                "service": "aider-proxy",
                "forwarding_to": self.server.upstream_base_url,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def _is_health_check(self) -> bool:
        path = self.path.split("?", 1)[0]
        return path in {"/", "/health", "/status", "/ready"}

    def _upstream_request_path(self) -> str:
        upstream_url = urllib.parse.urlsplit(self.server.upstream_base_url)
        target = urllib.parse.urlsplit(self.path)
        upstream_path = _join_upstream_path(upstream_url.path, target.path)
        if target.query:
            upstream_path += f"?{target.query}"
        return upstream_path

    def _log_exchange(
        self,
        *,
        stem: str,
        started_at: float,
        request_body: bytes,
        response_status: int | None,
        response_reason: str | None,
        response_headers: list[tuple[str, str]] | None,
        response_body: bytes | None,
        error: str | None = None,
    ) -> None:
        request_headers = _sanitize_headers(list(self.headers.items()))
        entry: dict[str, object] = {
            "ts": started_at,
            "duration_ms": int((time.time() - started_at) * 1000),
            "method": self.command,
            "path": self.path,
            "upstream": self._upstream_request_path(),
            "request": {
                "headers": request_headers,
                **_build_logged_body(
                    request_body,
                    request_headers,
                    body_path=self._write_blob(stem, "request", request_body),
                    inline_bodies=self.server.inline_bodies,
                ),
            },
        }

        if response_status is not None and response_headers is not None and response_body is not None:
            sanitized_response_headers = _sanitize_headers(response_headers)
            entry["response"] = {
                "status": response_status,
                "reason": response_reason,
                "headers": sanitized_response_headers,
                **_build_logged_body(
                    response_body,
                    sanitized_response_headers,
                    body_path=self._write_blob(stem, "response", response_body),
                    inline_bodies=self.server.inline_bodies,
                ),
            }

        if error is not None:
            entry["error"] = error

        self._log_json(entry)

    def _forward_http(self) -> None:
        started_at = time.time()
        stem = self._next_stem()
        request_body = self._read_body()

        if self._is_health_check():
            self._log_exchange(
                stem=stem,
                started_at=started_at,
                request_body=request_body,
                response_status=200,
                response_reason="OK",
                response_headers=[("Content-Type", "application/json")],
                response_body=json.dumps(
                    {
                        "ok": True,
                        "service": "aider-proxy",
                        "forwarding_to": self.server.upstream_base_url,
                    }
                ).encode("utf-8"),
            )
            self._health_response()
            return

        upstream_url = urllib.parse.urlsplit(self.server.upstream_base_url)
        upstream_path = self._upstream_request_path()

        headers = _build_forward_headers(
            list(self.headers.items()),
            upstream_url.netloc,
            preserve_accept_encoding=self.server.preserve_accept_encoding,
        )

        connection_cls = http.client.HTTPSConnection if upstream_url.scheme == "https" else http.client.HTTPConnection
        kwargs: dict[str, object] = {"timeout": self.server.upstream_timeout}
        if upstream_url.scheme == "https":
            kwargs["context"] = self.server.upstream_ssl_context
        conn = connection_cls(upstream_url.hostname, upstream_url.port, **kwargs)

        try:
            conn.request(self.command, upstream_path, body=request_body, headers=headers)
            upstream_response = conn.getresponse()

            response_headers = [
                (key, value)
                for key, value in upstream_response.getheaders()
                if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-length"
            ]

            self.send_response(upstream_response.status, upstream_response.reason)
            for key, value in response_headers:
                self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()

            chunks: list[bytes] = []
            while True:
                chunk = upstream_response.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                self.wfile.write(chunk)
                self.wfile.flush()

            response_body = b"".join(chunks)
            self.close_connection = True
            self._log_exchange(
                stem=stem,
                started_at=started_at,
                request_body=request_body,
                response_status=upstream_response.status,
                response_reason=upstream_response.reason,
                response_headers=response_headers,
                response_body=response_body,
            )
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self.send_response(502, "Bad Gateway")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            self._log_exchange(
                stem=stem,
                started_at=started_at,
                request_body=request_body,
                response_status=None,
                response_reason=None,
                response_headers=None,
                response_body=None,
                error=str(exc),
            )
        finally:
            conn.close()

    def do_GET(self) -> None:
        self._forward_http()

    def do_POST(self) -> None:
        self._forward_http()

    def do_PUT(self) -> None:
        self._forward_http()

    def do_PATCH(self) -> None:
        self._forward_http()

    def do_DELETE(self) -> None:
        self._forward_http()

    def do_OPTIONS(self) -> None:
        self._forward_http()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(fmt % args + "\n")


class ProxyServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        log_path: Path,
        bodies_dir: Path,
        upstream_base_url: str,
        upstream_timeout: float,
        upstream_ssl_context: ssl.SSLContext | None,
        preserve_accept_encoding: bool,
        inline_bodies: bool,
    ):
        super().__init__(server_address, ProxyHandler)
        self.log_path = log_path
        self.bodies_dir = bodies_dir
        self.upstream_base_url = upstream_base_url
        self.upstream_timeout = upstream_timeout
        self.upstream_ssl_context = upstream_ssl_context
        self.preserve_accept_encoding = preserve_accept_encoding
        self.inline_bodies = inline_bodies
        self.counter = 0
        self.counter_lock = threading.Lock()
        self.log_lock = threading.Lock()

    def next_id(self) -> int:
        with self.counter_lock:
            self.counter += 1
            return self.counter


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal OpenAI-compatible capture proxy for Aider.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18457, type=int)
    parser.add_argument("--upstream", default="https://api.openai.com/v1")
    parser.add_argument("--timeout", default=120.0, type=float)
    parser.add_argument("--log", default="../targets/aider/proxy-traffic.jsonl")
    parser.add_argument("--bodies-dir", default="../targets/aider/proxy-bodies")
    parser.add_argument("--cert-file")
    parser.add_argument("--key-file")
    parser.add_argument("--insecure-upstream", action="store_true")
    parser.add_argument(
        "--preserve-accept-encoding",
        action="store_true",
        help="Forward the client's Accept-Encoding header unchanged instead of forcing identity for readable capture logs.",
    )
    parser.add_argument(
        "--inline-bodies",
        action="store_true",
        help="Also inline base64-encoded request/response bodies into the JSONL log. Raw body files are always written.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    log_path = (root / args.log).resolve()
    bodies_dir = (root / args.bodies_dir).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    bodies_dir.mkdir(parents=True, exist_ok=True)

    upstream_url = urllib.parse.urlsplit(args.upstream)
    if upstream_url.scheme not in {"http", "https"}:
        raise SystemExit("--upstream must start with http:// or https://")
    if upstream_url.hostname is None:
        raise SystemExit("--upstream must include a hostname")

    upstream_ssl_context = None
    if upstream_url.scheme == "https":
        upstream_ssl_context = ssl.create_default_context()
        if args.insecure_upstream:
            upstream_ssl_context.check_hostname = False
            upstream_ssl_context.verify_mode = ssl.CERT_NONE

    server = ProxyServer(
        (args.host, args.port),
        log_path=log_path,
        bodies_dir=bodies_dir,
        upstream_base_url=args.upstream,
        upstream_timeout=args.timeout,
        upstream_ssl_context=upstream_ssl_context,
        preserve_accept_encoding=args.preserve_accept_encoding,
        inline_bodies=args.inline_bodies,
    )

    if args.cert_file and args.key_file:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.load_cert_chain(certfile=args.cert_file, keyfile=args.key_file)
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        local_url = f"https://{args.host}:{args.port}"
    elif args.cert_file or args.key_file:
        raise SystemExit("--cert-file and --key-file must be provided together")
    else:
        local_url = f"http://{args.host}:{args.port}"

    print(
        json.dumps(
            {
                "listening": local_url,
                "forwarding_to": args.upstream,
                "preserve_accept_encoding": args.preserve_accept_encoding,
                "inline_bodies": args.inline_bodies,
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
