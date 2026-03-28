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


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _maybe_json(body: bytes) -> Optional[dict]:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _sse_body(events: list[dict]) -> bytes:
    payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return payload.encode("utf-8") + b"data: [DONE]\n\n"


def _default_headers(body: bytes, *, content_type: str) -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Connection": "close",
        "Access-Control-Allow-Origin": "*",
    }


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ContinueProxy/0.1"

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

        exchange_id = self.server.next_exchange_id()
        started_at = time.time()
        request_path = _redact_query(self.path, log_secrets=self.server.log_secrets)

        request_stem = self.server.make_stem(exchange_id, started_at, "request", self.command, request_path)
        request_body_path = self.server.requests_dir / f"{request_stem}.bin"
        request_body_path.write_bytes(request_body)

        exchange = {
            "id": exchange_id,
            "started_at": started_at,
            "listener": self.server.listener_name,
            "request": {
                "method": self.command,
                "path": request_path,
                "headers": {
                    key: _redact_value(key, value, log_secrets=self.server.log_secrets)
                    for key, value in self.headers.items()
                },
                "body_path": str(request_body_path),
                "body_size": len(request_body),
            },
            "upstream": {
                "base_url": self.server.upstream_base_url,
            },
        }

        if self.path.split("?", 1)[0] in DEFAULT_HEALTH_PATHS:
            response_bytes = _json_body(
                {
                    "ok": True,
                    "service": "continue-proxy",
                    "listener": self.server.listener_name,
                    "mode": self.server.mode,
                    "upstream_base_url": self.server.upstream_base_url,
                }
            )
            headers = _default_headers(response_bytes, content_type="application/json")
            self._send_local_response(200, response_bytes, headers=headers)
            response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
            response_body_path = self.server.responses_dir / f"{response_stem}.bin"
            response_body_path.write_bytes(response_bytes)
            exchange["response"] = {
                "status": 200,
                "reason": "OK",
                "headers": headers,
                "body_path": str(response_body_path),
                "body_size": len(response_bytes),
            }
            exchange["note"] = "health"
            exchange["finished_at"] = time.time()
            exchange["duration_ms"] = round((exchange["finished_at"] - started_at) * 1000, 3)
            self.server.append_exchange(exchange)
            return

        upstream_response = None
        response_body_path = None

        try:
            if self.server.mode in {"forward", "forward-or-stub"}:
                connection = self.server.make_connection()
                upstream_target = self.server.build_upstream_target(self.path)
                forwarded_headers = self.server.build_upstream_headers(self.headers, len(request_body))
                exchange["upstream"]["target"] = upstream_target

                connection.request(self.command, upstream_target, body=request_body, headers=forwarded_headers)
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
                        if self.command != "HEAD":
                            self.wfile.write(chunk)
                    self.wfile.flush()

                exchange["response"] = {
                    "status": upstream_response.status,
                    "reason": upstream_response.reason,
                    "headers": response_headers,
                    "body_path": str(response_body_path),
                    "body_size": body_size,
                }
                exchange["note"] = "forwarded"
            else:
                raise ConnectionError("stub mode enabled")
        except Exception as exc:
            if self.server.mode == "forward":
                error_payload = _json_body(
                    {
                        "ok": False,
                        "error": "proxy_error",
                        "detail": str(exc),
                    }
                )
                headers = _default_headers(error_payload, content_type="application/json")
                self._send_local_response(502, error_payload, headers=headers)

                if response_body_path is None:
                    response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
                    response_body_path = self.server.responses_dir / f"{response_stem}.bin"
                response_body_path.write_bytes(error_payload)

                exchange["response"] = {
                    "status": 502,
                    "reason": "Bad Gateway",
                    "headers": headers,
                    "body_path": str(response_body_path),
                    "body_size": len(error_payload),
                }
                exchange["error"] = str(exc)
                exchange["note"] = "forward-error"
            else:
                status, reason, headers, response_bytes, note = self.server.build_stub_response(self.command, self.path, self.headers, request_body)
                self._send_local_response(status, response_bytes, headers=headers)

                if response_body_path is None:
                    response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
                    response_body_path = self.server.responses_dir / f"{response_stem}.bin"
                response_body_path.write_bytes(response_bytes)

                exchange["response"] = {
                    "status": status,
                    "reason": reason,
                    "headers": {
                        key: _redact_value(key, value, log_secrets=self.server.log_secrets)
                        for key, value in headers.items()
                    },
                    "body_path": str(response_body_path),
                    "body_size": len(response_bytes),
                }
                exchange["note"] = note
                exchange["error"] = str(exc)
        finally:
            if upstream_response is not None:
                upstream_response.close()

        exchange["finished_at"] = time.time()
        exchange["duration_ms"] = round((exchange["finished_at"] - started_at) * 1000, 3)
        self.server.append_exchange(exchange)

    def _send_local_response(self, status: int, response_bytes: bytes, *, headers: Optional[dict[str, str]] = None) -> None:
        self.send_response(status)
        effective_headers = headers or _default_headers(response_bytes, content_type="application/json")
        for key, value in effective_headers.items():
            self.send_header(key, value)
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
        request_body = self._read_body()
        self.close_connection = True

        exchange_id = self.server.next_exchange_id()
        started_at = time.time()
        request_path = _redact_query(self.path, log_secrets=self.server.log_secrets)
        request_stem = self.server.make_stem(exchange_id, started_at, "request", self.command, request_path)
        request_body_path = self.server.requests_dir / f"{request_stem}.bin"
        request_body_path.write_bytes(request_body)

        response_bytes = b""
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD",
            "Content-Length": "0",
            "Connection": "close",
        }
        self._send_local_response(204, response_bytes, headers=headers)

        response_stem = self.server.make_stem(exchange_id, time.time(), "response", self.command, request_path)
        response_body_path = self.server.responses_dir / f"{response_stem}.bin"
        response_body_path.write_bytes(response_bytes)

        exchange = {
            "id": exchange_id,
            "started_at": started_at,
            "listener": self.server.listener_name,
            "request": {
                "method": self.command,
                "path": request_path,
                "headers": {
                    key: _redact_value(key, value, log_secrets=self.server.log_secrets)
                    for key, value in self.headers.items()
                },
                "body_path": str(request_body_path),
                "body_size": len(request_body),
            },
            "upstream": {
                "base_url": self.server.upstream_base_url,
            },
            "response": {
                "status": 204,
                "reason": "No Content",
                "headers": headers,
                "body_path": str(response_body_path),
                "body_size": 0,
            },
            "note": "preflight",
        }
        exchange["finished_at"] = time.time()
        exchange["duration_ms"] = round((exchange["finished_at"] - started_at) * 1000, 3)
        self.server.append_exchange(exchange)

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
        mode: str,
        request_timeout: int,
        log_secrets: bool,
        upstream_auth_header: Optional[str],
        upstream_auth_value: Optional[str],
        exchanges_log_path: Path,
        requests_dir: Path,
        responses_dir: Path,
    ):
        super().__init__(server_address, handler_cls)
        self.listener_name = listener_name
        self.upstream = upstream
        self.upstream_base_url = upstream_base_url
        self.mode = mode
        self.request_timeout = request_timeout
        self.log_secrets = log_secrets
        self.upstream_auth_header = upstream_auth_header
        self.upstream_auth_value = upstream_auth_value
        self.exchanges_log_path = exchanges_log_path
        self.requests_dir = requests_dir
        self.responses_dir = responses_dir
        self._exchange_lock = threading.Lock()
        self._exchange_counter = 0

    def next_exchange_id(self) -> int:
        with self._exchange_lock:
            self._exchange_counter += 1
            return self._exchange_counter

    def append_exchange(self, exchange: dict) -> None:
        with self._exchange_lock:
            with self.exchanges_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(exchange) + "\n")

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

    def build_upstream_headers(self, headers, body_length: int) -> dict[str, str]:
        forwarded = {}
        for key, value in headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower == "host":
                continue
            if lower == "content-length":
                continue
            forwarded[key] = value
        forwarded["Host"] = self.upstream.netloc
        forwarded["Content-Length"] = str(body_length)
        # Prefer uncompressed upstream bodies so captured provider traffic stays readable.
        forwarded["Accept-Encoding"] = "identity"
        if self.upstream_auth_header and self.upstream_auth_value:
            forwarded[self.upstream_auth_header] = self.upstream_auth_value
        return forwarded

    def build_stub_response(
        self, method: str, raw_path: str, headers, request_body: bytes
    ) -> tuple[int, str, dict[str, str], bytes, str]:
        path = raw_path.split("?", 1)[0]
        request_json = _maybe_json(request_body) or {}
        accepts_sse = headers.get("Accept") == "text/event-stream" or request_json.get("stream") is True

        if path.endswith("/models"):
            response_bytes = _json_body(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "gpt-4o-mini",
                            "object": "model",
                            "created": 0,
                            "owned_by": "openai",
                        }
                    ],
                }
            )
            return 200, "OK", _default_headers(response_bytes, content_type="application/json"), response_bytes, "stub-models"

        if path.endswith("/responses"):
            if accepts_sse:
                response_bytes = _sse_body(
                    [
                        {"type": "response.created", "response": {"id": "resp_continue_proxy", "status": "in_progress"}},
                        {"type": "response.output_text.delta", "delta": "continue-proxy stub"},
                        {
                            "type": "response.completed",
                            "response": {
                                "id": "resp_continue_proxy",
                                "status": "completed",
                                "output": [
                                    {
                                        "id": "msg_continue_proxy",
                                        "type": "message",
                                        "status": "completed",
                                        "role": "assistant",
                                        "content": [{"type": "output_text", "text": "continue-proxy stub"}],
                                    }
                                ],
                                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                            },
                        },
                    ]
                )
                return 200, "OK", _default_headers(response_bytes, content_type="text/event-stream"), response_bytes, "stub-responses-sse"

            response_bytes = _json_body(
                {
                    "id": "resp_continue_proxy",
                    "object": "response",
                    "status": "completed",
                    "output": [
                        {
                            "id": "msg_continue_proxy",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "continue-proxy stub"}],
                        }
                    ],
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                }
            )
            return 200, "OK", _default_headers(response_bytes, content_type="application/json"), response_bytes, "stub-responses-json"

        if path.endswith("/chat/completions"):
            if accepts_sse:
                response_bytes = _sse_body(
                    [
                        {
                            "id": "chatcmpl-continue-proxy",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": request_json.get("model", "gpt-4o-mini"),
                            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                        },
                        {
                            "id": "chatcmpl-continue-proxy",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": request_json.get("model", "gpt-4o-mini"),
                            "choices": [{"index": 0, "delta": {"content": "continue-proxy stub"}, "finish_reason": None}],
                        },
                        {
                            "id": "chatcmpl-continue-proxy",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": request_json.get("model", "gpt-4o-mini"),
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        },
                    ]
                )
                return 200, "OK", _default_headers(response_bytes, content_type="text/event-stream"), response_bytes, "stub-chat-sse"

            response_bytes = _json_body(
                {
                    "id": "chatcmpl-continue-proxy",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request_json.get("model", "gpt-4o-mini"),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "continue-proxy stub"},
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            )
            return 200, "OK", _default_headers(response_bytes, content_type="application/json"), response_bytes, "stub-chat-json"

        response_bytes = _json_body(
            {
                "id": "resp_continue_proxy",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_continue_proxy",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "continue-proxy stub"}],
                    }
                ],
            }
        )
        return 200, "OK", _default_headers(response_bytes, content_type="application/json"), response_bytes, "stub-generic"


def _serve_http(server: ProxyServer) -> None:
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Continue CLI model traffic through an OpenAI-compatible proxy.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18431)
    parser.add_argument("--https-port", type=int, default=None)
    parser.add_argument("--cert", default=None, help="PEM certificate for the HTTPS listener.")
    parser.add_argument("--key", default=None, help="PEM private key for the HTTPS listener.")
    parser.add_argument("--upstream", default="https://api.openai.com")
    parser.add_argument("--mode", choices=["stub", "forward", "forward-or-stub"], default="forward-or-stub")
    parser.add_argument("--request-timeout", type=int, default=120)
    parser.add_argument("--log-secrets", action="store_true")
    parser.add_argument(
        "--upstream-auth-header",
        default=None,
        help="Header name to inject on forwarded upstream requests, for example Authorization.",
    )
    parser.add_argument(
        "--upstream-auth-value",
        default=None,
        help="Header value to inject on forwarded upstream requests, for example 'Bearer sk-...'.",
    )
    parser.add_argument("--exchanges-log", default="../targets/continue/proxy-exchanges.jsonl")
    parser.add_argument("--requests-dir", default="../targets/continue/proxy-requests")
    parser.add_argument("--responses-dir", default="../targets/continue/proxy-responses")
    args = parser.parse_args()

    upstream = urlsplit(args.upstream)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname:
        raise SystemExit(f"Unsupported upstream URL: {args.upstream}")

    if args.https_port is not None and (not args.cert or not args.key):
        raise SystemExit("--https-port requires both --cert and --key")

    root = Path(__file__).resolve().parent
    exchanges_log_path = (root / args.exchanges_log).resolve()
    requests_dir = (root / args.requests_dir).resolve()
    responses_dir = (root / args.responses_dir).resolve()
    exchanges_log_path.parent.mkdir(parents=True, exist_ok=True)
    requests_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)

    http_server = ProxyServer(
        (args.host, args.port),
        ProxyHandler,
        listener_name="http",
        upstream=upstream,
        upstream_base_url=args.upstream,
        mode=args.mode,
        request_timeout=args.request_timeout,
        log_secrets=args.log_secrets,
        upstream_auth_header=args.upstream_auth_header,
        upstream_auth_value=args.upstream_auth_value,
        exchanges_log_path=exchanges_log_path,
        requests_dir=requests_dir,
        responses_dir=responses_dir,
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
            mode=args.mode,
            request_timeout=args.request_timeout,
            log_secrets=args.log_secrets,
            upstream_auth_header=args.upstream_auth_header,
            upstream_auth_value=args.upstream_auth_value,
            exchanges_log_path=exchanges_log_path,
            requests_dir=requests_dir,
            responses_dir=responses_dir,
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
                "service": "continue-proxy",
                "http": f"http://{args.host}:{args.port}",
                "https": f"https://{args.host}:{args.https_port}" if args.https_port is not None else None,
                "mode": args.mode,
                "upstream": args.upstream,
                "exchanges_log": str(exchanges_log_path),
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
