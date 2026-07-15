"""Backend auth + payload shaping, especially reaching OpenAI-compatible
*cloud* providers (DeepSeek, Groq, Together, OpenRouter, ...) through the
`custom` backend: point base_url at the provider, pass an api_key, and the
request must carry Bearer auth, usage reporting, and `max_tokens`."""

import json
import unittest
from unittest import mock

import promptchain.streaming as streaming
from promptchain.backends import auth_headers, chat_completions_url


class TestAuthHeaders(unittest.TestCase):
    def test_bearer_whenever_key_present(self):
        # Any backend with a key gets Bearer auth — not just the named clouds.
        for backend in ("openai", "gemini", "custom", "lmstudio", "ollama"):
            self.assertEqual(
                auth_headers(backend, "sk-abc"),
                {"Authorization": "Bearer sk-abc"},
                backend,
            )

    def test_no_header_without_key(self):
        for backend in ("openai", "custom", "lmstudio", "ollama"):
            self.assertEqual(auth_headers(backend, ""), {}, backend)


class _FakeSSEResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)


def _capture_post(backend, api_key, base_url, model="m"):
    """Run one streamed completion and return the captured requests.post call."""
    lines = [b'data: {"choices":[{"delta":{"content":"hi"}}]}', b"data: [DONE]"]
    with mock.patch.object(
        streaming.requests, "post", return_value=_FakeSSEResponse(lines)
    ) as post:
        list(streaming.stream_completion(
            base_url=base_url, model=model, user_message="x",
            backend=backend, api_key=api_key,
        ))
    return post.call_args


class TestCustomCloud(unittest.TestCase):
    def test_deepseek_via_custom(self):
        call = _capture_post("custom", "sk-deepseek", "https://api.deepseek.com",
                             model="deepseek-chat")
        url = call.args[0]
        headers = call.kwargs["headers"]
        payload = call.kwargs["json"]
        self.assertEqual(url, "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer sk-deepseek")
        # OpenAI-compatible clouds use max_tokens, not max_completion_tokens
        self.assertIn("max_tokens", payload)
        self.assertNotIn("max_completion_tokens", payload)
        # usage reporting requested for a keyed endpoint
        self.assertEqual(payload["stream_options"], {"include_usage": True})

    def test_groq_and_openrouter_base_urls(self):
        # The /v1/chat/completions convention holds when base_url is the part
        # before /v1 (matches Groq, Together, OpenRouter, Fireworks, ...).
        self.assertEqual(
            chat_completions_url("https://api.groq.com/openai", "custom"),
            "https://api.groq.com/openai/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_url("https://openrouter.ai/api", "custom"),
            "https://openrouter.ai/api/v1/chat/completions",
        )

    def test_custom_local_keyless_sends_no_auth_or_usage(self):
        call = _capture_post("custom", "", "http://localhost:8080")
        headers = call.kwargs["headers"]
        payload = call.kwargs["json"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("stream_options", payload)  # minimal servers may choke

    def test_openai_backend_still_uses_max_completion_tokens(self):
        call = _capture_post("openai", "sk", "https://api.openai.com")
        payload = call.kwargs["json"]
        self.assertIn("max_completion_tokens", payload)
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["stream_options"], {"include_usage": True})


if __name__ == "__main__":
    unittest.main()
