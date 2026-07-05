"""Tests for the Anthropic streaming path — focused on the sampling-parameter
(`temperature`) handling, which 400s on Opus 4.7/4.8 and Fable models but is
accepted on Opus 4.6 / Sonnet 4.6 / Haiku 4.5.

No live API calls: the Anthropic SDK client is replaced with a fake whose
`messages.stream(**kwargs)` records the kwargs and either returns canned tokens
or raises a real anthropic exception. This exercises the known-model fast-path
skip, the forward-compatible retry-without-temperature, system extraction,
usage reporting, and the error mapping contract app.py relies on.
"""

import json
import unittest
from unittest import mock

import anthropic
import httpx

import core.streaming as streaming
from core.streaming import ThinkTagFilter


def _bad_request(message: str) -> anthropic.BadRequestError:
    """Build a real anthropic.BadRequestError carrying the given message."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        400,
        request=request,
        json={"type": "error", "error": {"type": "invalid_request_error", "message": message}},
    )
    return anthropic.BadRequestError(message, response=response, body=None)


class _FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeStream:
    """Stands in for the context manager returned by client.messages.stream()."""

    def __init__(self, tokens, usage=None):
        self._tokens = tokens
        self._usage = usage or _FakeUsage(11, 22)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(self._tokens)

    def get_final_message(self):
        msg = mock.Mock()
        msg.usage = self._usage
        return msg


class _FakeMessages:
    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


class _FakeClient:
    def __init__(self, behaviors):
        self.messages = _FakeMessages(behaviors)


def _run(model, behaviors, *, temperature=0.5, usage_out=None):
    """Run stream_completion's anthropic path against a fake client.
    Returns (collected_tokens, fake_messages)."""
    fake = _FakeClient(behaviors)
    with mock.patch.object(anthropic, "Anthropic", lambda **kw: fake):
        tokens = list(
            streaming.stream_completion(
                base_url="https://api.anthropic.com",
                model=model,
                system_prompt="You are helpful.",
                user_message="hi",
                temperature=temperature,
                backend="anthropic",
                api_key="sk-test",
                usage_out=usage_out,
            )
        )
    return tokens, fake.messages


class TestThinkTagFilter(unittest.TestCase):
    def _run_filter(self, chunks):
        f = ThinkTagFilter()
        visible = "".join(f.feed(c) for c in chunks)
        visible += f.flush()
        return visible, f.reasoning

    def test_basic_strip(self):
        visible, reasoning = self._run_filter(["<think>plan</think>hello"])
        self.assertEqual(visible, "hello")
        self.assertEqual(reasoning, "plan")

    def test_tags_split_across_chunks(self):
        visible, reasoning = self._run_filter(
            ["<th", "ink>reas", "oning</th", "ink>\n\nanswer"]
        )
        self.assertEqual(visible, "answer")
        self.assertEqual(reasoning, "reasoning")

    def test_no_think_block_passes_through(self):
        visible, reasoning = self._run_filter(["hello ", "world"])
        self.assertEqual(visible, "hello world")
        self.assertEqual(reasoning, "")

    def test_think_tag_later_in_output_is_kept(self):
        # Only a block that OPENS the output counts as reasoning
        visible, reasoning = self._run_filter(["code about ", "<think> tags"])
        self.assertEqual(visible, "code about <think> tags")
        self.assertEqual(reasoning, "")

    def test_leading_whitespace_before_block(self):
        visible, reasoning = self._run_filter(["\n <think>hm</think>\n\nok"])
        self.assertEqual(visible, "ok")
        self.assertEqual(reasoning, "hm")

    def test_partial_open_that_never_completes_is_flushed(self):
        visible, _ = self._run_filter(["<think"])
        self.assertEqual(visible, "<think")

    def test_lookalike_word_passes_through(self):
        visible, _ = self._run_filter(["<thinker>text"])
        self.assertEqual(visible, "<thinker>text")

    def test_unterminated_block_is_all_reasoning(self):
        visible, reasoning = self._run_filter(["<think>never ", "ends"])
        self.assertEqual(visible, "")
        self.assertEqual(reasoning, "never ends")


class _FakeSSEResponse:
    """Minimal stand-in for a streaming requests.Response."""

    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode()


def _content(text: str) -> bytes:
    return _sse({"choices": [{"delta": {"content": text}}]})


def _collect_openai(lines, reasoning_out=None):
    """Run the OpenAI-compatible path against canned SSE lines."""
    fake = _FakeSSEResponse(lines + [b"data: [DONE]"])
    with mock.patch.object(streaming.requests, "post", return_value=fake):
        return list(
            streaming.stream_completion(
                base_url="http://localhost:1234",
                model="local-model",
                system_prompt="sys",
                user_message="hi",
                backend="lmstudio",
                reasoning_out=reasoning_out,
            )
        )


class TestOpenAIReasoningStream(unittest.TestCase):
    def test_inline_think_block_stripped_and_collected(self):
        reasoning: dict = {}
        tokens = _collect_openai(
            [_content("<th"), _content("ink>plan"), _content("</think>"), _content("code")],
            reasoning_out=reasoning,
        )
        self.assertEqual("".join(tokens), "code")
        self.assertEqual(reasoning.get("text"), "plan")

    def test_reasoning_content_field_collected(self):
        reasoning: dict = {}
        tokens = _collect_openai(
            [
                _sse({"choices": [{"delta": {"reasoning_content": "thinking "}}]}),
                _sse({"choices": [{"delta": {"reasoning_content": "hard"}}]}),
                _content("answer"),
            ],
            reasoning_out=reasoning,
        )
        self.assertEqual("".join(tokens), "answer")
        self.assertEqual(reasoning.get("text"), "thinking hard")

    def test_plain_stream_unchanged(self):
        tokens = _collect_openai([_content("a"), _content("b")])
        self.assertEqual("".join(tokens), "ab")


class TestOmitsTemperature(unittest.TestCase):
    def test_known_models_omit(self):
        for m in ("claude-opus-4-7", "claude-opus-4-8", "claude-fable-5", "CLAUDE-OPUS-4-8"):
            self.assertTrue(streaming._anthropic_omits_temperature(m), m)

    def test_other_models_keep(self):
        for m in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"):
            self.assertFalse(streaming._anthropic_omits_temperature(m), m)


class TestSamplingParamError(unittest.TestCase):
    def test_matches_temperature_message(self):
        self.assertTrue(
            streaming._is_sampling_param_error(
                _bad_request("temperature: Extra inputs are not permitted")
            )
        )

    def test_ignores_unrelated_message(self):
        self.assertFalse(
            streaming._is_sampling_param_error(_bad_request("messages: roles must alternate"))
        )


class TestAnthropicStreaming(unittest.TestCase):
    def test_known_model_skips_temperature(self):
        tokens, msgs = _run("claude-opus-4-8", [_FakeStream(["ok"])])
        self.assertEqual(tokens, ["ok"])
        self.assertEqual(len(msgs.calls), 1)
        self.assertNotIn("temperature", msgs.calls[0])

    def test_other_model_sends_temperature(self):
        _tokens, msgs = _run("claude-opus-4-6", [_FakeStream(["ok"])], temperature=0.4)
        self.assertEqual(msgs.calls[0]["temperature"], 0.4)

    def test_system_prompt_extracted_to_top_level(self):
        _tokens, msgs = _run("claude-opus-4-6", [_FakeStream(["ok"])])
        self.assertEqual(msgs.calls[0]["system"], "You are helpful.")
        # System message is lifted out of the conversation turns
        roles = [m.get("role") for m in msgs.calls[0]["messages"]]
        self.assertNotIn("system", roles)

    def test_usage_out_populated(self):
        usage = {}
        _run("claude-opus-4-6", [_FakeStream(["a", "b"], _FakeUsage(7, 9))], usage_out=usage)
        self.assertEqual(usage, {"input_tokens": 7, "output_tokens": 9})

    def test_retries_without_temperature_on_sampling_400(self):
        # A model not in the fast-path list that nonetheless rejects temperature:
        # first attempt 400s, retry drops the param and streams successfully.
        behaviors = [
            _bad_request("temperature: unexpected parameter"),
            _FakeStream(["hello", " world"]),
        ]
        tokens, msgs = _run("claude-opus-4-9", behaviors)
        self.assertEqual(tokens, ["hello", " world"])
        self.assertEqual(len(msgs.calls), 2)
        self.assertIn("temperature", msgs.calls[0])     # first try sent it
        self.assertNotIn("temperature", msgs.calls[1])  # retry dropped it

    def test_non_sampling_400_is_not_retried(self):
        behaviors = [_bad_request("messages: roles must alternate")]
        with self.assertRaises(RuntimeError):
            _run("claude-opus-4-6", behaviors)

    def test_timeout_maps_to_timeout_error(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        with self.assertRaises(TimeoutError):
            _run("claude-opus-4-6", [anthropic.APITimeoutError(request=request)])

    def test_auth_error_maps_to_runtime_error(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(401, request=request, json={"error": {"message": "bad key"}})
        err = anthropic.AuthenticationError("bad key", response=response, body=None)
        with self.assertRaises(RuntimeError):
            _run("claude-opus-4-6", [err])


if __name__ == "__main__":
    unittest.main()
