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

    def test_no_header_for_local(self):
        self.assertEqual(api._auth_headers("lmstudio", "sk-abc"), {})

    def test_no_header_without_key(self):
        self.assertEqual(api._auth_headers("openai", ""), {})


class TestUnloadNoOp(unittest.TestCase):
    @mock.patch("core.api.requests.post")
    def test_cloud_unload_makes_no_request(self, mock_post):
        for backend in ("openai", "anthropic", "gemini", "custom"):
            self.assertFalse(api.unload_model("https://x", "m", backend))
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
