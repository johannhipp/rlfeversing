#!/usr/bin/env python3

import argparse
import base64
import http.client
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def clean_headers(headers: Dict[str, str]) -> Dict[str, str]:
    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    }
    cleaned = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}
    # Keep upstream captures readable instead of storing compressed blobs.
    cleaned["Accept-Encoding"] = "identity"
    return cleaned


def maybe_json(body: bytes) -> Optional[dict]:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


class CaptureServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        log_path: Path,
        bodies_dir: Path,
        upstream: Optional[str],
        mode: str,
    ):
        super().__init__(server_address, handler_cls)
        self.log_path = log_path
        self.bodies_dir = bodies_dir
        self.counter = 0
        self.upstream = upstream.rstrip("/") if upstream else None
        self.mode = mode

    def next_stem(self, method: str, path: str) -> str:
        self.counter += 1
        now = time.time()
        return f"{self.counter:04d}-{int(now)}-{safe_name(method)}-{safe_name(path)[:80]}"


class CaptureHandler(BaseHTTPRequestHandler):
    server_version = "OpencodeProxy/0.1"

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            return self.rfile.read(int(length))
        except Exception:
            return b""

    def _write_bytes(self, path: Path, data: bytes) -> str:
        path.write_bytes(data)
        return str(path)

    def _append_log(self, entry: dict) -> None:
        with self.server.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def _resolve_upstream(self) -> Tuple[Optional[str], str]:
        if self.path.startswith("http://") or self.path.startswith("https://"):
            return self.path, self.path
        if not self.server.upstream:
            return None, self.path
        return urljoin(self.server.upstream + "/", self.path.lstrip("/")), self.path

    def _log_exchange(
        self,
        *,
        request_body: bytes,
        response_status: int,
        response_headers: Dict[str, str],
        response_body: bytes,
        upstream_url: Optional[str],
        note: Optional[str] = None,
        upstream_error: Optional[str] = None,
    ) -> None:
        stem = self.server.next_stem(self.command, self.path)
        request_body_path = self.server.bodies_dir / f"{stem}-request.bin"
        response_body_path = self.server.bodies_dir / f"{stem}-response.bin"
        self._write_bytes(request_body_path, request_body)
        self._write_bytes(response_body_path, response_body)
        entry = {
            "ts": time.time(),
            "method": self.command,
            "path": self.path,
            "client": self.client_address[0],
            "headers": {k: v for k, v in self.headers.items()},
            "body_b64": base64.b64encode(request_body).decode("ascii"),
            "body_path": str(request_body_path),
            "upstream_url": upstream_url,
            "response": {
                "status": response_status,
                "headers": response_headers,
                "body_b64": base64.b64encode(response_body).decode("ascii"),
                "body_path": str(response_body_path),
            },
        }
        if note:
            entry["note"] = note
        if upstream_error:
            entry["upstream_error"] = upstream_error
        self._append_log(entry)

    def _send(self, status: int, headers: Dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _health(self, request_body: bytes) -> None:
        payload = {
            "ok": True,
            "service": "opencode-proxy",
            "mode": self.server.mode,
            "upstream": self.server.upstream,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Access-Control-Allow-Origin": "*",
        }
        self._log_exchange(
            request_body=request_body,
            response_status=200,
            response_headers=headers,
            response_body=body,
            upstream_url=None,
            note="health",
        )
        self._send(200, headers, body)

    def _stub_response(self, request_body: bytes) -> None:
        request_json = maybe_json(request_body) or {}
        accepts_sse = self.headers.get("Accept") == "text/event-stream" or request_json.get("stream") is True
        path = self.path.split("?", 1)[0]

        if path.endswith("/models"):
            payload = {
                "object": "list",
                "data": [
                    {
                        "id": "gpt-5.2",
                        "object": "model",
                        "created": 0,
                        "owned_by": "openai",
                    }
                ],
            }
            body = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Access-Control-Allow-Origin": "*",
            }
            self._log_exchange(
                request_body=request_body,
                response_status=200,
                response_headers=headers,
                response_body=body,
                upstream_url=None,
                note="stub-models",
            )
            self._send(200, headers, body)
            return

        if accepts_sse or path.endswith("/responses"):
            events = [
                {
                    "type": "response.created",
                    "response": {"id": "resp_proxy", "status": "in_progress"},
                },
                {"type": "response.output_text.delta", "delta": "proxy stub"},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_proxy",
                        "status": "completed",
                        "output": [
                            {
                                "id": "msg_proxy",
                                "type": "message",
                                "status": "completed",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "proxy stub"}],
                            }
                        ],
                        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                    },
                },
            ]
            body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8") + b"data: [DONE]\n\n"
            headers = {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "close",
                "Content-Length": str(len(body)),
                "Access-Control-Allow-Origin": "*",
            }
            self._log_exchange(
                request_body=request_body,
                response_status=200,
                response_headers=headers,
                response_body=body,
                upstream_url=None,
                note="stub-sse",
            )
            self._send(200, headers, body)
            return

        if path.endswith("/chat/completions"):
            payload = {
                "id": "chatcmpl-proxy",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request_json.get("model", "proxy-model"),
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "proxy stub"},
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        else:
            payload = {
                "id": "resp_proxy",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_proxy",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "proxy stub"}],
                    }
                ],
            }

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Access-Control-Allow-Origin": "*",
        }
        self._log_exchange(
            request_body=request_body,
            response_status=200,
            response_headers=headers,
            response_body=body,
            upstream_url=None,
            note="stub-json",
        )
        self._send(200, headers, body)

    def _forward(self, request_body: bytes) -> bool:
        upstream_url, _original_path = self._resolve_upstream()
        if not upstream_url:
            return False

        split = urlsplit(upstream_url)
        target_path = split.path or "/"
        if split.query:
            target_path += f"?{split.query}"
        headers = clean_headers({k: v for k, v in self.headers.items()})

        connection_cls = http.client.HTTPSConnection if split.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(split.hostname, split.port, timeout=30)
        try:
            connection.request(self.command, target_path, body=request_body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            response_headers = {k: v for k, v in response.getheaders()}
            response_headers.pop("Transfer-Encoding", None)
            response_headers["Content-Length"] = str(len(response_body))
            self._log_exchange(
                request_body=request_body,
                response_status=response.status,
                response_headers=response_headers,
                response_body=response_body,
                upstream_url=upstream_url,
                note="forwarded",
            )
            self._send(response.status, response_headers, response_body)
            return True
        except (OSError, URLError, http.client.HTTPException) as exc:
            if self.server.mode == "forward":
                body = json.dumps({"ok": False, "error": str(exc), "upstream_url": upstream_url}).encode("utf-8")
                headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "Access-Control-Allow-Origin": "*",
                }
                self._log_exchange(
                    request_body=request_body,
                    response_status=502,
                    response_headers=headers,
                    response_body=body,
                    upstream_url=upstream_url,
                    note="forward-error",
                    upstream_error=str(exc),
                )
                self._send(502, headers, body)
                return True

            self._log_exchange(
                request_body=request_body,
                response_status=599,
                response_headers={},
                response_body=b"",
                upstream_url=upstream_url,
                note="forward-fallback",
                upstream_error=str(exc),
            )
            return False
        finally:
            connection.close()

    def _dispatch(self) -> None:
        request_body = self._read_body()
        path = self.path.split("?", 1)[0]

        if path in {"/", "/health", "/ready", "/api/health", "/status"}:
            self._health(request_body)
            return

        if self.server.mode in {"forward", "forward-or-stub"} and self._forward(request_body):
            return

        self._stub_response(request_body)

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        request_body = self._read_body()
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD",
            "Content-Length": "0",
        }
        self._log_exchange(
            request_body=request_body,
            response_status=204,
            response_headers=headers,
            response_body=b"",
            upstream_url=None,
            note="preflight",
        )
        self._send(204, headers, b"")

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(fmt % args + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture proxy for opencode provider traffic.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18456, type=int)
    parser.add_argument("--upstream", default="https://api.openai.com")
    parser.add_argument("--mode", choices=["stub", "forward", "forward-or-stub"], default="forward-or-stub")
    parser.add_argument("--log", default="../targets/opencode/proxy-requests.jsonl")
    parser.add_argument("--bodies-dir", default="../targets/opencode/proxy-bodies")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    log_path = (root / args.log).resolve()
    bodies_dir = (root / args.bodies_dir).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    bodies_dir.mkdir(parents=True, exist_ok=True)

    server = CaptureServer(
        (args.host, args.port),
        CaptureHandler,
        log_path=log_path,
        bodies_dir=bodies_dir,
        upstream=args.upstream,
        mode=args.mode,
    )
    print(
        json.dumps(
            {
                "listening": f"http://{args.host}:{args.port}",
                "log_path": str(log_path),
                "bodies_dir": str(bodies_dir),
                "mode": args.mode,
                "upstream": args.upstream,
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
