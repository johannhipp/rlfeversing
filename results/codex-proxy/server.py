#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import http.client
import json
import socket
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


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _sanitize_headers(headers: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers:
        out[key] = "<redacted>" if key.lower() in SENSITIVE_HEADERS else value
    return out


def _maybe_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _join_upstream_path(base_path: str, request_path: str) -> str:
    normalized_base = base_path.rstrip("/")
    normalized_request = request_path or "/"
    if not normalized_request.startswith("/"):
        normalized_request = f"/{normalized_request}"

    # Codex already includes the configured base path in redirected requests,
    # e.g. /v1/responses when openai_base_url ends with /v1.
    if normalized_base and (
        normalized_request == normalized_base or normalized_request.startswith(f"{normalized_base}/")
    ):
        return normalized_request

    joined = f"{normalized_base}{normalized_request}"
    return joined or "/"


class WebSocketFrameLogger:
    def __init__(self, handler: "ProxyHandler", *, stem: str, direction: str):
        self.handler = handler
        self.stem = stem
        self.direction = direction
        self.buffer = b""
        self.message_opcode: int | None = None
        self.message_parts: list[bytes] = []

    def feed(self, data: bytes) -> None:
        self.buffer += data
        while True:
            frame = self._take_frame()
            if frame is None:
                return
            opcode, fin, payload = frame
            self._handle_frame(opcode=opcode, fin=fin, payload=payload)

    def flush(self) -> None:
        if self.buffer:
            self.handler._log_json(
                {
                    "ts": time.time(),
                    "kind": "websocket_incomplete_frame",
                    "path": self.handler.path,
                    "ws_id": self.stem,
                    "direction": self.direction,
                    "bytes_b64": base64.b64encode(self.buffer).decode("ascii"),
                }
            )
            self.buffer = b""
        if self.message_parts:
            self._emit_message(kind="incomplete_message", payload=b"".join(self.message_parts))
            self.message_parts = []
            self.message_opcode = None

    def _take_frame(self) -> tuple[int, bool, bytes] | None:
        if len(self.buffer) < 2:
            return None

        b1 = self.buffer[0]
        b2 = self.buffer[1]
        fin = bool(b1 & 0x80)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        offset = 2

        if length == 126:
            if len(self.buffer) < offset + 2:
                return None
            length = int.from_bytes(self.buffer[offset : offset + 2], "big")
            offset += 2
        elif length == 127:
            if len(self.buffer) < offset + 8:
                return None
            length = int.from_bytes(self.buffer[offset : offset + 8], "big")
            offset += 8

        mask_key = b""
        if masked:
            if len(self.buffer) < offset + 4:
                return None
            mask_key = self.buffer[offset : offset + 4]
            offset += 4

        if len(self.buffer) < offset + length:
            return None

        payload = self.buffer[offset : offset + length]
        self.buffer = self.buffer[offset + length :]

        if masked:
            payload = bytes(byte ^ mask_key[idx % 4] for idx, byte in enumerate(payload))

        return opcode, fin, payload

    def _handle_frame(self, *, opcode: int, fin: bool, payload: bytes) -> None:
        if opcode in {0x8, 0x9, 0xA}:
            kind = {0x8: "close", 0x9: "ping", 0xA: "pong"}[opcode]
            self._emit_message(kind=kind, payload=payload)
            return

        if opcode in {0x1, 0x2}:
            self.message_opcode = opcode
            self.message_parts = [payload]
        elif opcode == 0x0:
            self.message_parts.append(payload)
        else:
            self._emit_message(kind=f"opcode_{opcode}", payload=payload)
            return

        if fin:
            joined = b"".join(self.message_parts)
            kind = "text" if self.message_opcode == 0x1 else "binary"
            self._emit_message(kind=kind, payload=joined)
            self.message_parts = []
            self.message_opcode = None

    def _emit_message(self, *, kind: str, payload: bytes) -> None:
        entry: dict[str, object] = {
            "ts": time.time(),
            "kind": "websocket_message",
            "path": self.handler.path,
            "ws_id": self.stem,
            "direction": self.direction,
            "message_type": kind,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }
        text = _maybe_utf8(payload)
        if text is not None:
            entry["payload_text"] = text
        body_path = self.handler._write_blob(self.stem, f"ws-{self.direction}-{kind}", payload)
        entry["payload_path"] = body_path
        self.handler._log_json(entry)


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CodexProxy/0.1"

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
        entry: dict[str, object] = {
            "ts": started_at,
            "method": self.command,
            "path": self.path,
            "request": {
                "headers": _sanitize_headers(list(self.headers.items())),
                "body_b64": base64.b64encode(request_body).decode("ascii"),
                "body_path": self._write_blob(stem, "request", request_body),
            },
        }

        if response_headers is not None and response_body is not None and response_status is not None:
            entry["response"] = {
                "status": response_status,
                "reason": response_reason,
                "headers": _sanitize_headers(response_headers),
                "body_b64": base64.b64encode(response_body).decode("ascii"),
                "body_path": self._write_blob(stem, "response", response_body),
            }

        if error is not None:
            entry["error"] = error

        self._log_json(entry)

    def _is_websocket_upgrade(self) -> bool:
        connection = self.headers.get("Connection", "")
        upgrade = self.headers.get("Upgrade", "")
        return "upgrade" in connection.lower() and upgrade.lower() == "websocket"

    def _upstream_request_path(self) -> str:
        upstream_url = urllib.parse.urlsplit(self.server.upstream_base_url)
        target = urllib.parse.urlsplit(self.path)
        upstream_path = _join_upstream_path(upstream_url.path, target.path)
        if target.query:
            upstream_path += f"?{target.query}"
        return upstream_path

    def _open_upstream_socket(self) -> socket.socket:
        upstream_url = urllib.parse.urlsplit(self.server.upstream_base_url)
        port = upstream_url.port or (443 if upstream_url.scheme == "https" else 80)
        conn = socket.create_connection((upstream_url.hostname, port), timeout=self.server.upstream_timeout)
        if upstream_url.scheme == "https":
            assert self.server.upstream_ssl_context is not None
            conn = self.server.upstream_ssl_context.wrap_socket(conn, server_hostname=upstream_url.hostname)
        conn.settimeout(self.server.upstream_timeout)
        return conn

    def _read_http_head(self, conn: socket.socket) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        return data

    def _split_http_head(self, data: bytes) -> tuple[bytes, bytes]:
        marker = b"\r\n\r\n"
        idx = data.find(marker)
        if idx == -1:
            return data, b""
        head_end = idx + len(marker)
        return data[:head_end], data[head_end:]

    def _parse_http_head(self, raw_head: bytes) -> tuple[str, list[tuple[str, str]]]:
        text = raw_head.decode("iso-8859-1", errors="replace")
        lines = text.split("\r\n")
        status_line = lines[0] if lines else ""
        headers: list[tuple[str, str]] = []
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers.append((key.strip(), value.strip()))
        return status_line, headers

    def _forward_http(self) -> None:
        started_at = time.time()
        stem = self._next_stem()
        request_body = self._read_body()

        upstream_url = urllib.parse.urlsplit(self.server.upstream_base_url)
        upstream_path = self._upstream_request_path()

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }
        headers["Host"] = upstream_url.netloc
        headers["Connection"] = "close"

        connection_cls = http.client.HTTPSConnection if upstream_url.scheme == "https" else http.client.HTTPConnection
        kwargs = {"timeout": self.server.upstream_timeout}
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

    def _forward_websocket(self) -> None:
        started_at = time.time()
        stem = self._next_stem()
        upstream_url = urllib.parse.urlsplit(self.server.upstream_base_url)
        upstream_path = self._upstream_request_path()
        request_lines = [f"{self.command} {upstream_path} HTTP/1.1", f"Host: {upstream_url.netloc}"]
        for key, value in self.headers.items():
            if key.lower() == "host":
                continue
            request_lines.append(f"{key}: {value}")
        raw_request = ("\r\n".join(request_lines) + "\r\n\r\n").encode("iso-8859-1")

        upstream_conn: socket.socket | None = None
        client_parser = WebSocketFrameLogger(self, stem=stem, direction="client_to_upstream")
        upstream_parser = WebSocketFrameLogger(self, stem=stem, direction="upstream_to_client")

        try:
            upstream_conn = self._open_upstream_socket()
            upstream_conn.sendall(raw_request)
            raw_response = self._read_http_head(upstream_conn)
            raw_head, leftover = self._split_http_head(raw_response)
            self.connection.sendall(raw_response)

            status_line, response_headers = self._parse_http_head(raw_head)
            self._log_json(
                {
                    "ts": started_at,
                    "kind": "websocket_handshake",
                    "method": self.command,
                    "path": self.path,
                    "ws_id": stem,
                    "request": {
                        "headers": _sanitize_headers(list(self.headers.items())),
                    },
                    "response": {
                        "status_line": status_line,
                        "headers": _sanitize_headers(response_headers),
                        "head_b64": base64.b64encode(raw_head).decode("ascii"),
                    },
                }
            )

            if leftover:
                upstream_parser.feed(leftover)

            stop_event = threading.Event()

            def relay(src: socket.socket, dst: socket.socket, parser: WebSocketFrameLogger) -> None:
                try:
                    while not stop_event.is_set():
                        chunk = src.recv(4096)
                        if not chunk:
                            return
                        parser.feed(chunk)
                        dst.sendall(chunk)
                except Exception as exc:
                    self._log_json(
                        {
                            "ts": time.time(),
                            "kind": "websocket_relay_error",
                            "path": self.path,
                            "ws_id": stem,
                            "direction": parser.direction,
                            "error": str(exc),
                        }
                    )
                finally:
                    stop_event.set()

            threads = [
                threading.Thread(target=relay, args=(self.connection, upstream_conn, client_parser), daemon=True),
                threading.Thread(target=relay, args=(upstream_conn, self.connection, upstream_parser), daemon=True),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self.send_response(502, "Bad Gateway")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            self._log_json(
                {
                    "ts": started_at,
                    "kind": "websocket_handshake_error",
                    "method": self.command,
                    "path": self.path,
                    "ws_id": stem,
                    "request": {
                        "headers": _sanitize_headers(list(self.headers.items())),
                    },
                    "error": str(exc),
                }
            )
        finally:
            client_parser.flush()
            upstream_parser.flush()
            if upstream_conn is not None:
                try:
                    upstream_conn.close()
                except OSError:
                    pass

    def do_GET(self) -> None:
        if self._is_websocket_upgrade():
            self._forward_websocket()
            return
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
    ):
        super().__init__(server_address, ProxyHandler)
        self.log_path = log_path
        self.bodies_dir = bodies_dir
        self.upstream_base_url = upstream_base_url
        self.upstream_timeout = upstream_timeout
        self.upstream_ssl_context = upstream_ssl_context
        self.counter = 0
        self.counter_lock = threading.Lock()
        self.log_lock = threading.Lock()

    def next_id(self) -> int:
        with self.counter_lock:
            self.counter += 1
            return self.counter


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal reverse proxy for capturing Codex traffic.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18456, type=int)
    parser.add_argument("--upstream", default="https://api.openai.com/v1")
    parser.add_argument("--timeout", default=120.0, type=float)
    parser.add_argument("--log", default="../targets/codex/proxy-requests.jsonl")
    parser.add_argument("--bodies-dir", default="../targets/codex/proxy-bodies")
    parser.add_argument("--cert-file")
    parser.add_argument("--key-file")
    parser.add_argument("--insecure-upstream", action="store_true")
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
