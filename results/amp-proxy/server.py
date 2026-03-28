#!/usr/bin/env python3

import argparse
import base64
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


class CaptureHandler(BaseHTTPRequestHandler):
    server_version = "AmpProxy/0.1"

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            return self.rfile.read(int(length))
        except Exception:
            return b""

    def _log_request(self, body: bytes) -> None:
        now = time.time()
        entry = {
            "ts": now,
            "method": self.command,
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body_b64": base64.b64encode(body).decode("ascii"),
        }

        self.server.counter += 1
        idx = self.server.counter
        stem = f"{idx:04d}-{int(now)}-{_safe_name(self.command)}-{_safe_name(self.path)[:80]}"
        body_path = self.server.bodies_dir / f"{stem}.bin"
        body_path.write_bytes(body)
        entry["body_path"] = str(body_path)

        with self.server.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, status: int, text: str, content_type: str = "text/plain") -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        body = self._read_body()
        self._log_request(body)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        body = self._read_body()
        self._log_request(body)
        self._dispatch()

    def do_POST(self) -> None:
        body = self._read_body()
        self._log_request(body)
        self._dispatch()

    def do_PUT(self) -> None:
        body = self._read_body()
        self._log_request(body)
        self._dispatch()

    def do_PATCH(self) -> None:
        body = self._read_body()
        self._log_request(body)
        self._dispatch()

    def do_DELETE(self) -> None:
        body = self._read_body()
        self._log_request(body)
        self._dispatch()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(fmt % args + "\n")

    def _dispatch(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in {"/", "/health", "/api/health", "/status", "/api/status", "/ready"}:
            self._send_json(
                200,
                {
                    "ok": True,
                    "status": "ready",
                    "service": "amp-proxy",
                    "note": "Capture proxy response",
                },
            )
            return

        if path.endswith("/events") or self.headers.get("Accept") == "text/event-stream":
            self._send_text(200, "", "text/event-stream")
            return

        self._send_json(
            200,
            {
                "ok": True,
                "status": "ready",
                "path": path,
                "method": self.command,
                "note": "Generic capture proxy response",
            },
        )


class CaptureServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_cls, *, log_path: Path, bodies_dir: Path):
        super().__init__(server_address, handler_cls)
        self.log_path = log_path
        self.bodies_dir = bodies_dir
        self.counter = 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18317, type=int)
    parser.add_argument("--log", default="../targets/amp/proxy-requests.jsonl")
    parser.add_argument("--bodies-dir", default="../targets/amp/proxy-bodies")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    log_path = (root / args.log).resolve()
    bodies_dir = (root / args.bodies_dir).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    bodies_dir.mkdir(parents=True, exist_ok=True)

    server = CaptureServer((args.host, args.port), CaptureHandler, log_path=log_path, bodies_dir=bodies_dir)
    print(json.dumps({"listening": f"http://{args.host}:{args.port}", "log_path": str(log_path)}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
