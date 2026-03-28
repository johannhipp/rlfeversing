#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

import server


class JoinUpstreamPathTests(unittest.TestCase):
    def test_preserves_existing_prefixed_path(self) -> None:
        self.assertEqual(server._join_upstream_path("/v1", "/v1/chat/completions"), "/v1/chat/completions")

    def test_adds_prefix_when_missing(self) -> None:
        self.assertEqual(server._join_upstream_path("/v1", "/chat/completions"), "/v1/chat/completions")

    def test_handles_empty_base(self) -> None:
        self.assertEqual(server._join_upstream_path("", "/models"), "/models")


class HeaderForwardingTests(unittest.TestCase):
    def test_rewrites_host_and_accept_encoding(self) -> None:
        headers = server._build_forward_headers(
            [("Authorization", "secret"), ("Host", "old"), ("Accept-Encoding", "gzip")],
            "api.openai.com",
            preserve_accept_encoding=False,
        )
        self.assertEqual(headers["Host"], "api.openai.com")
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertEqual(headers["Connection"], "close")

    def test_can_preserve_accept_encoding(self) -> None:
        headers = server._build_forward_headers(
            [("Accept-Encoding", "gzip, br")],
            "api.openai.com",
            preserve_accept_encoding=True,
        )
        self.assertEqual(headers["Accept-Encoding"], "gzip, br")


class MetadataTests(unittest.TestCase):
    def test_body_metadata_includes_digest(self) -> None:
        metadata = server._build_body_metadata(b"hello", {"Content-Type": "text/plain"})
        self.assertEqual(
            metadata["sha256"],
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        )

    def test_extracts_request_json_summary(self) -> None:
        metadata = server._build_body_metadata(
            (
                b'{"model":"gpt-4o-mini","stream":true,"messages":[{"role":"user","content":"hi"}],'
                b'"tools":[{"type":"function","function":{"name":"search"}}]}'
            ),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(metadata["json_summary"]["model"], "gpt-4o-mini")
        self.assertEqual(metadata["json_summary"]["stream"], True)
        self.assertEqual(metadata["json_summary"]["messages_count"], 1)
        self.assertEqual(metadata["json_summary"]["tools_count"], 1)

    def test_extracts_response_json_summary(self) -> None:
        metadata = server._build_body_metadata(
            (
                b'{"id":"resp_123","object":"chat.completion","model":"gpt-4o-mini","choices":[{}],'
                b'"usage":{"prompt_tokens":10,"completion_tokens":3,"total_tokens":13}}'
            ),
            {"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertEqual(metadata["json_summary"]["id"], "resp_123")
        self.assertEqual(metadata["json_summary"]["choices_count"], 1)
        self.assertEqual(metadata["json_summary"]["usage"]["total_tokens"], 13)

    def test_extracts_error_summary(self) -> None:
        metadata = server._build_body_metadata(
            b'{"error":{"type":"invalid_request_error","code":"bad_request","message":"xxxxxxxxxx"}}',
            {"Content-Type": "application/json"},
        )
        self.assertEqual(metadata["json_summary"]["error"]["type"], "invalid_request_error")

    def test_redacts_sensitive_headers(self) -> None:
        sanitized = server._sanitize_headers(
            [("Authorization", "secret"), ("Content-Type", "application/json")]
        )
        self.assertEqual(sanitized["Authorization"], "<redacted>")
        self.assertEqual(sanitized["Content-Type"], "application/json")


class LoggedBodyTests(unittest.TestCase):
    def test_logged_body_uses_file_backed_metadata_by_default(self) -> None:
        logged = server._build_logged_body(
            b"hello",
            {"Content-Type": "text/plain"},
            body_path="/tmp/request.bin",
            inline_bodies=False,
        )
        self.assertEqual(logged["body_path"], "/tmp/request.bin")
        self.assertNotIn("body_b64", logged)

    def test_logged_body_can_inline_base64_when_requested(self) -> None:
        logged = server._build_logged_body(
            b"hello",
            {"Content-Type": "text/plain"},
            body_path="/tmp/request.bin",
            inline_bodies=True,
        )
        self.assertEqual(logged["body_b64"], "aGVsbG8=")


if __name__ == "__main__":
    unittest.main()
