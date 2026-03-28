from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from urllib.parse import urlsplit


MODULE_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("claude_code_proxy_server", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)


class _FakeHeaders:
    def __init__(self, pairs: list[tuple[str, str]]):
        self._pairs = pairs

    def items(self):
        return list(self._pairs)


class ProxyServerTests(unittest.TestCase):
    def make_server(
        self,
        *,
        upstream: str = "https://api.anthropic.com",
        log_secrets: bool = False,
        preserve_accept_encoding: bool = False,
    ):
        server = SERVER.ProxyServer.__new__(SERVER.ProxyServer)
        server.upstream = urlsplit(upstream)
        server.log_secrets = log_secrets
        server.preserve_accept_encoding = preserve_accept_encoding
        return server

    def test_redact_query_hides_secret_tokens(self):
        path = "/v1/messages?api_key=abc123&token=xyz&name=kept"
        self.assertEqual(
            SERVER._redact_query(path, log_secrets=False),
            "/v1/messages?api_key=%3Credacted%3E&token=%3Credacted%3E&name=kept",
        )

    def test_redact_query_can_preserve_secrets(self):
        path = "/v1/messages?api_key=abc123"
        self.assertEqual(SERVER._redact_query(path, log_secrets=True), path)

    def test_join_upstream_path_avoids_double_prefix(self):
        self.assertEqual(SERVER._join_upstream_path("/proxy", "/proxy/v1/messages"), "/proxy/v1/messages")
        self.assertEqual(SERVER._join_upstream_path("/proxy", "/v1/messages"), "/proxy/v1/messages")

    def test_is_local_health_path_ignores_query(self):
        self.assertTrue(SERVER._is_local_health_path("/health"))
        self.assertTrue(SERVER._is_local_health_path("/health?check=1"))
        self.assertFalse(SERVER._is_local_health_path("/v1/messages"))

    def test_build_upstream_target_keeps_query(self):
        server = self.make_server(upstream="https://api.anthropic.com/base")
        self.assertEqual(
            server.build_upstream_target("/v1/messages?beta=true"),
            "/base/v1/messages?beta=true",
        )

    def test_build_upstream_headers_forces_identity_by_default(self):
        server = self.make_server()
        headers = _FakeHeaders(
            [
                ("Authorization", "Bearer secret"),
                ("Accept-Encoding", "gzip"),
                ("Host", "127.0.0.1:18441"),
                ("Content-Length", "999"),
                ("X-Test", "1"),
            ]
        )
        forwarded = server.build_upstream_headers(headers, 12)
        self.assertEqual(forwarded["Host"], "api.anthropic.com")
        self.assertEqual(forwarded["Content-Length"], "12")
        self.assertEqual(forwarded["Accept-Encoding"], "identity")
        self.assertEqual(forwarded["Authorization"], "Bearer secret")
        self.assertEqual(forwarded["X-Test"], "1")
        self.assertNotIn("Content-Length", {k for k, _ in headers.items() if k != "Content-Length"})

    def test_build_upstream_headers_can_preserve_client_encoding(self):
        server = self.make_server(preserve_accept_encoding=True)
        headers = _FakeHeaders([("Accept-Encoding", "gzip"), ("Host", "127.0.0.1:18441")])
        forwarded = server.build_upstream_headers(headers, 0)
        self.assertEqual(forwarded["Accept-Encoding"], "gzip")

    def test_build_logged_target_url_redacts_query_by_default(self):
        server = self.make_server()
        target = server.build_logged_target_url("/v1/messages?api_key=abc123&model=claude")
        self.assertEqual(target, "https://api.anthropic.com/v1/messages?api_key=%3Credacted%3E&model=claude")

    def test_build_logged_target_url_can_keep_query_with_log_secrets(self):
        server = self.make_server(log_secrets=True)
        target = server.build_logged_target_url("/v1/messages?api_key=abc123")
        self.assertEqual(target, "https://api.anthropic.com/v1/messages?api_key=abc123")


if __name__ == "__main__":
    unittest.main()
