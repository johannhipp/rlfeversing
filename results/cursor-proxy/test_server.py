#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

import server


class JoinUpstreamPathTests(unittest.TestCase):
    def test_preserves_existing_prefixed_path(self) -> None:
        self.assertEqual(server._join_upstream_path("/api", "/api/list"), "/api/list")

    def test_adds_prefix_when_missing(self) -> None:
        self.assertEqual(server._join_upstream_path("/api", "/list"), "/api/list")

    def test_handles_empty_base(self) -> None:
        self.assertEqual(server._join_upstream_path("", "/list"), "/list")


class RedactionTests(unittest.TestCase):
    def test_redacts_sensitive_headers(self) -> None:
        self.assertEqual(
            server._redact_value("Authorization", "Bearer abc", log_secrets=False),
            "<redacted>",
        )

    def test_redacts_sensitive_query_values(self) -> None:
        self.assertEqual(
            server._redact_query("/v1/chat?token=abc&ok=1", log_secrets=False),
            "/v1/chat?token=%3Credacted%3E&ok=1",
        )

    def test_preserves_query_when_logging_secrets(self) -> None:
        self.assertEqual(
            server._redact_query("/v1/chat?token=abc&ok=1", log_secrets=True),
            "/v1/chat?token=abc&ok=1",
        )


if __name__ == "__main__":
    unittest.main()
