"""Foundry Gemma client and Content Safety helpers (no live Azure)."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from fnol_shadow.content_safety import content_safety_check, content_safety_enabled
from fnol_shadow.foundry import FoundryClient


class FoundryClientTests(unittest.TestCase):
    def test_chat_parses_openai_shape(self):
        payload = {
            "choices": [{"message": {"content": "Handler summary for the case."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        def fake_post(url, *, headers, body, timeout, sleeper, max_attempts=3):
            self.assertIn("gemma-4-31b", url)
            self.assertEqual(body["temperature"], 1.0)
            self.assertEqual(body["top_p"], 0.95)
            self.assertEqual(body["max_tokens"], 1200)
            return 200, {}, payload

        client = FoundryClient(
            endpoint="https://example.openai.azure.com",
            api_key="test-key",
            deployment="gemma-4-31b",
            content_safety=lambda _text: None,
        )
        with mock.patch("fnol_shadow.foundry._post_json", side_effect=fake_post):
            reply = client.chat("system", "user")
        self.assertEqual(reply.text, "Handler summary for the case.")
        self.assertEqual(reply.input_tokens, 10)
        self.assertEqual(reply.output_tokens, 5)
        self.assertIsNone(reply.guardrail_action)

    def test_content_safety_intervened(self):
        client = FoundryClient(
            endpoint="https://example.openai.azure.com",
            api_key="test-key",
            content_safety=lambda _text: "INTERVENED",
        )
        payload = {
            "choices": [{"message": {"content": "bad text here for summary"}, "finish_reason": "stop"}],
            "usage": {},
        }
        with mock.patch("fnol_shadow.foundry._post_json", return_value=(200, {}, payload)):
            reply = client.chat("system", "user")
        self.assertEqual(reply.guardrail_action, "INTERVENED")


class ContentSafetyTests(unittest.TestCase):
    def test_disabled_without_endpoint(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FNOL_CONTENT_SAFETY_ENDPOINT", None)
            self.assertFalse(content_safety_enabled())
            self.assertIsNone(content_safety_check("anything long enough"))


if __name__ == "__main__":
    unittest.main()
