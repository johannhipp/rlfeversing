import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server


def _ws_frame(opcode: int, payload: bytes, *, fin: bool = True, masked: bool = False) -> bytes:
    first = opcode | (0x80 if fin else 0)
    length = len(payload)
    if length >= 126:
        raise ValueError("test helper only supports short payloads")

    second = length | (0x80 if masked else 0)
    frame = bytearray([first, second])
    if masked:
        mask_key = b"\x01\x02\x03\x04"
        frame.extend(mask_key)
        payload = bytes(byte ^ mask_key[idx % 4] for idx, byte in enumerate(payload))
    frame.extend(payload)
    return bytes(frame)


class _FakeHandler:
    def __init__(self, root: Path):
        self.path = "/v1/responses"
        self.root = root
        self.entries: list[dict[str, object]] = []

    def _write_blob(self, stem: str, suffix: str, data: bytes) -> str:
        path = self.root / f"{stem}-{suffix}.bin"
        path.write_bytes(data)
        return str(path)

    def _log_json(self, entry: dict[str, object]) -> None:
        self.entries.append(entry)


class JoinUpstreamPathTests(unittest.TestCase):
    def test_reuses_existing_v1_prefix(self) -> None:
        self.assertEqual(server._join_upstream_path("/v1", "/v1/responses"), "/v1/responses")

    def test_prepends_v1_prefix_when_missing(self) -> None:
        self.assertEqual(server._join_upstream_path("/v1", "/models"), "/v1/models")

    def test_handles_empty_base_path(self) -> None:
        self.assertEqual(server._join_upstream_path("", "/responses"), "/responses")


class SanitizeHeaderTests(unittest.TestCase):
    def test_redacts_sensitive_headers(self) -> None:
        sanitized = server._sanitize_headers(
            [
                ("Authorization", "Bearer secret"),
                ("X-Api-Key", "secret"),
                ("Content-Type", "application/json"),
            ]
        )
        self.assertEqual(sanitized["Authorization"], "<redacted>")
        self.assertEqual(sanitized["X-Api-Key"], "<redacted>")
        self.assertEqual(sanitized["Content-Type"], "application/json")


class WebSocketFrameLoggerTests(unittest.TestCase):
    def test_decodes_masked_fragmented_text_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler = _FakeHandler(Path(tmp))
            logger = server.WebSocketFrameLogger(
                handler,
                stem="0001",
                direction="client_to_upstream",
            )

            logger.feed(_ws_frame(0x1, b"hel", fin=False, masked=True))
            logger.feed(_ws_frame(0x0, b"lo", fin=True, masked=True))

            self.assertEqual(len(handler.entries), 1)
            entry = handler.entries[0]
            self.assertEqual(entry["kind"], "websocket_message")
            self.assertEqual(entry["message_type"], "text")
            self.assertEqual(entry["payload_text"], "hello")
            self.assertEqual(base64.b64decode(entry["payload_b64"]), b"hello")
            self.assertTrue(Path(entry["payload_path"]).is_file())

    def test_logs_control_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler = _FakeHandler(Path(tmp))
            logger = server.WebSocketFrameLogger(
                handler,
                stem="0002",
                direction="upstream_to_client",
            )

            logger.feed(_ws_frame(0x9, b"ping", masked=False))

            self.assertEqual(len(handler.entries), 1)
            entry = handler.entries[0]
            self.assertEqual(entry["message_type"], "ping")
            self.assertEqual(base64.b64decode(entry["payload_b64"]), b"ping")

    def test_flush_reports_incomplete_frame_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler = _FakeHandler(Path(tmp))
            logger = server.WebSocketFrameLogger(
                handler,
                stem="0003",
                direction="client_to_upstream",
            )

            logger.feed(b"\x81")
            logger.flush()

            self.assertEqual(len(handler.entries), 1)
            entry = handler.entries[0]
            self.assertEqual(entry["kind"], "websocket_incomplete_frame")
            self.assertEqual(base64.b64decode(entry["bytes_b64"]), b"\x81")


if __name__ == "__main__":
    unittest.main()
