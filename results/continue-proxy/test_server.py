#!/usr/bin/env python3

from pathlib import Path
import sys
import types
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

import server


class JoinUpstreamPathTests(unittest.TestCase):
    def test_preserves_existing_prefixed_path(self) -> None:
        self.assertEqual(server._join_upstream_path("/v1", "/v1/responses"), "/v1/responses")

    def test_adds_prefix_when_missing(self) -> None:
        self.assertEqual(server._join_upstream_path("/v1", "/models"), "/v1/models")

    def test_handles_empty_base(self) -> None:
        self.assertEqual(server._join_upstream_path("", "/models"), "/models")


class RedactionTests(unittest.TestCase):
    def test_redacts_sensitive_headers(self) -> None:
        self.assertEqual(
            server._redact_value("Authorization", "Bearer abc", log_secrets=False),
            "<redacted>",
        )

    def test_preserves_headers_when_logging_secrets(self) -> None:
        self.assertEqual(
            server._redact_value("Authorization", "Bearer abc", log_secrets=True),
            "Bearer abc",
        )

    def test_redacts_sensitive_query_values(self) -> None:
        self.assertEqual(
            server._redact_query("/v1/chat?token=abc&ok=1", log_secrets=False),
            "/v1/chat?token=%3Credacted%3E&ok=1",
        )


class HeaderForwardingTests(unittest.TestCase):
    def test_rewrites_host_and_content_length(self) -> None:
        dummy = types.SimpleNamespace(
            upstream=types.SimpleNamespace(netloc="api.openai.com"),
            upstream_auth_header=None,
            upstream_auth_value=None,
        )
        forwarded = server.ProxyServer.build_upstream_headers(
            dummy,
            {
                "Host": "127.0.0.1:18431",
                "Authorization": "Bearer abc",
                "Content-Length": "999",
                "Connection": "keep-alive",
                "Content-Type": "application/json",
            },
            12,
        )

        self.assertEqual(forwarded["Host"], "api.openai.com")
        self.assertEqual(forwarded["Content-Length"], "12")
        self.assertEqual(forwarded["Authorization"], "Bearer abc")
        self.assertEqual(forwarded["Content-Type"], "application/json")
        self.assertEqual(forwarded["Accept-Encoding"], "identity")
        self.assertNotIn("Connection", forwarded)

    def test_can_override_upstream_auth(self) -> None:
        dummy = types.SimpleNamespace(
            upstream=types.SimpleNamespace(netloc="api.openai.com"),
            upstream_auth_header="Authorization",
            upstream_auth_value="Bearer real-key",
        )
        forwarded = server.ProxyServer.build_upstream_headers(
            dummy,
            {
                "Authorization": "Bearer dummy",
                "Content-Length": "1",
            },
            2,
        )

        self.assertEqual(forwarded["Authorization"], "Bearer real-key")


class StubResponseTests(unittest.TestCase):
    def test_stub_responses_sse_shape(self) -> None:
        dummy = types.SimpleNamespace()
        status, reason, headers, response_bytes, note = server.ProxyServer.build_stub_response(
            dummy,
            "POST",
            "/v1/responses",
            {"Accept": "text/event-stream"},
            b'{"stream": true}',
        )

        self.assertEqual(status, 200)
        self.assertEqual(reason, "OK")
        self.assertEqual(note, "stub-responses-sse")
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertIn(b"response.created", response_bytes)
        self.assertIn(b"[DONE]", response_bytes)

    def test_stub_chat_completions_json_shape(self) -> None:
        dummy = types.SimpleNamespace()
        status, reason, headers, response_bytes, note = server.ProxyServer.build_stub_response(
            dummy,
            "POST",
            "/v1/chat/completions",
            {"Content-Type": "application/json"},
            b'{"model":"gpt-4.1-mini","stream":false}',
        )

        payload = server.json.loads(response_bytes.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(reason, "OK")
        self.assertEqual(note, "stub-chat-json")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(payload["object"], "chat.completion")
        self.assertEqual(payload["model"], "gpt-4.1-mini")
        self.assertEqual(payload["choices"][0]["message"]["content"], "continue-proxy stub")


if __name__ == "__main__":
    unittest.main()
