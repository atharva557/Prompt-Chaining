"""Tests for backend URL builders, cloud detection, and unload short-circuits.

No live API calls — these exercise pure construction logic and the no-op
guards. The one network-touching path (unload) is verified to *not* fire for
cloud/custom backends via a patched requests.post.
"""

import unittest
from unittest import mock

import core.api as api


class TestIsCloud(unittest.TestCase):
    def test_cloud_backends(self):
        for b in ("openai", "anthropic", "gemini"):
            self.assertTrue(api.is_cloud(b))

    def test_local_backends(self):
        for b in ("lmstudio", "ollama", "custom"):
            self.assertFalse(api.is_cloud(b))


class TestUrlBuilders(unittest.TestCase):
    def test_chat_completions_openai_compatible(self):
        self.assertEqual(
            api.chat_completions_url("http://localhost:1234", "lmstudio"),
            "http://localhost:1234/v1/chat/completions",
        )
        self.assertEqual(
            api.chat_completions_url("https://api.openai.com", "openai"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_chat_completions_gemini_path_quirk(self):
        # Gemini's base already includes /v1beta/openai — no extra /v1
        self.assertEqual(
            api.chat_completions_url(
                "https://generativelanguage.googleapis.com/v1beta/openai", "gemini"
            ),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )

    def test_trailing_slash_is_normalized(self):
        self.assertEqual(
            api.chat_completions_url("http://localhost:1234/", "lmstudio"),
            "http://localhost:1234/v1/chat/completions",
        )

    def test_models_url_per_backend(self):
        self.assertEqual(
            api.models_url("http://localhost:11434", "ollama"),
            "http://localhost:11434/api/tags",
        )
        self.assertEqual(
            api.models_url("http://localhost:1234", "lmstudio"),
            "http://localhost:1234/v1/models",
        )
        self.assertEqual(
            api.models_url(
                "https://generativelanguage.googleapis.com/v1beta/openai", "gemini"
            ),
            "https://generativelanguage.googleapis.com/v1beta/openai/models",
        )


class TestAuthHeaders(unittest.TestCase):
    def test_bearer_for_cloud_with_key(self):
        self.assertEqual(
            api._auth_headers("openai", "sk-abc"),
            {"Authorization": "Bearer sk-abc"},
        )

    def test_bearer_for_any_keyed_backend(self):
        # Keys ride along whenever provided — that's how OpenAI-compatible
        # clouds (DeepSeek, Groq, ...) work through the `custom` backend.
        # Keyless local servers (the normal case) still get no header.
        self.assertEqual(
            api._auth_headers("lmstudio", "sk-abc"),
            {"Authorization": "Bearer sk-abc"},
        )

    def test_no_header_without_key(self):
        self.assertEqual(api._auth_headers("openai", ""), {})


class TestEstimateCost(unittest.TestCase):
    def test_known_model_input_plus_output(self):
        # Opus 4.8: $5/M in + $25/M out → 1M of each = $30
        self.assertAlmostEqual(
            api.estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000), 30.0
        )

    def test_substring_match_with_suffix(self):
        self.assertIsNotNone(api.estimate_cost("gpt-4o-mini-2024-07-18", 1000, 1000))

    def test_mini_matched_before_base(self):
        # gpt-4o-mini must match its own (cheaper) row, not gpt-4o
        mini = api.estimate_cost("gpt-4o-mini", 1_000_000, 0)
        base = api.estimate_cost("gpt-4o", 1_000_000, 0)
        self.assertLess(mini, base)

    def test_unknown_model_returns_none(self):
        self.assertIsNone(api.estimate_cost("llama-3-8b-instruct", 1000, 1000))

    def test_missing_token_counts_return_none(self):
        self.assertIsNone(api.estimate_cost("claude-opus-4-8", None, 100))
        self.assertIsNone(api.estimate_cost("", 100, 100))


class TestUnloadNoOp(unittest.TestCase):
    @mock.patch("core.api.requests.post")
    def test_cloud_unload_makes_no_request(self, mock_post):
        for backend in ("openai", "anthropic", "gemini", "custom"):
            self.assertFalse(api.unload_model("https://x", "m", backend))
        mock_post.assert_not_called()


class TestScheduleUnload(unittest.TestCase):
    """The idle-unload timer (threading.Timer mocked — no real waiting)."""

    def tearDown(self):
        api.cancel_unload()          # never leave a live timer between tests
        api.consume_unload_fired()   # ...nor a stale fired flag

    @mock.patch("core.api.threading.Timer")
    def test_arms_timer_for_local_backend(self, MockTimer):
        armed = api.schedule_unload("http://localhost:1234", "m", "lmstudio", 300)
        self.assertTrue(armed)
        MockTimer.assert_called_once_with(
            300, api._fire_unload, args=("http://localhost:1234", "m", "lmstudio")
        )
        MockTimer.return_value.start.assert_called_once()

    @mock.patch("promptchain.lifecycle.unload_model")
    def test_fire_unload_unloads_and_sets_flag(self, mock_unload):
        api._fire_unload("http://localhost:1234", "m", "lmstudio")
        mock_unload.assert_called_once_with("http://localhost:1234", "m", "lmstudio")
        self.assertTrue(api.consume_unload_fired())
        self.assertFalse(api.consume_unload_fired())  # one-shot

    def test_fired_flag_starts_false(self):
        self.assertFalse(api.consume_unload_fired())

    @mock.patch("core.api.threading.Timer")
    def test_no_op_for_cloud_custom_and_zero_delay(self, MockTimer):
        self.assertFalse(api.schedule_unload("https://x", "m", "openai", 300))
        self.assertFalse(api.schedule_unload("https://x", "m", "anthropic", 300))
        self.assertFalse(api.schedule_unload("http://x", "m", "custom", 300))
        self.assertFalse(api.schedule_unload("http://localhost:1234", "m", "lmstudio", 0))
        MockTimer.assert_not_called()

    @mock.patch("core.api.threading.Timer")
    def test_rearm_cancels_previous_timer(self, MockTimer):
        first, second = mock.Mock(), mock.Mock()
        MockTimer.side_effect = [first, second]
        api.schedule_unload("http://localhost:1234", "m", "lmstudio", 300)
        api.schedule_unload("http://localhost:1234", "m", "lmstudio", 300)
        first.cancel.assert_called_once()  # previous timer cancelled on re-arm

    @mock.patch("core.api.threading.Timer")
    def test_cancel_unload_stops_pending_timer(self, MockTimer):
        timer = MockTimer.return_value
        api.schedule_unload("http://localhost:1234", "m", "lmstudio", 300)
        api.cancel_unload()
        timer.cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
