"""Hermes tool-call support: the ToolCallFilter stream filter, native
OpenAI-style tool_calls delta accumulation, tools= passthrough, and the
StreamingResponse wrapper."""

import json
import unittest
from unittest import mock

import promptchain.streaming as streaming
from promptchain.streaming import StreamingResponse, ToolCallFilter


class TestToolCallFilter(unittest.TestCase):
    def _run(self, chunks):
        f = ToolCallFilter()
        visible = "".join(f.feed(c) for c in chunks)
        visible += f.flush()
        return visible, f.tool_calls

    def test_basic_extraction(self):
        visible, calls = self._run([
            'Checking the weather.\n<tool_call>\n'
            '{"name": "get_weather", "arguments": {"city": "Paris"}}\n'
            '</tool_call>\nDone.'
        ])
        self.assertEqual(visible, "Checking the weather.\n\nDone.")
        self.assertEqual(calls, [
            {"id": None, "name": "get_weather", "arguments": {"city": "Paris"}}
        ])

    def test_tags_split_across_chunks(self):
        visible, calls = self._run([
            "before <tool", '_call>{"na', 'me": "f", "argum',
            'ents": {"x": 1}}</tool', "_call> after",
        ])
        self.assertEqual(visible, "before  after")
        self.assertEqual(calls, [{"id": None, "name": "f", "arguments": {"x": 1}}])

    def test_multiple_calls(self):
        _visible, calls = self._run([
            '<tool_call>{"name": "a", "arguments": {}}</tool_call>',
            '<tool_call>{"name": "b", "arguments": {}}</tool_call>',
        ])
        self.assertEqual([c["name"] for c in calls], ["a", "b"])

    def test_malformed_json_kept_raw(self):
        _visible, calls = self._run(["<tool_call>not json</tool_call>"])
        self.assertEqual(calls, [{"id": None, "name": "", "arguments": "not json"}])

    def test_unterminated_call_salvaged_at_flush(self):
        visible, calls = self._run(['<tool_call>{"name": "a", "arguments": {}}'])
        self.assertEqual(visible, "")
        self.assertEqual(calls[0]["name"], "a")

    def test_partial_open_that_never_completes_is_flushed(self):
        visible, calls = self._run(["text <tool_ca"])
        self.assertEqual(visible, "text <tool_ca")
        self.assertEqual(calls, [])

    def test_plain_text_untouched(self):
        visible, calls = self._run(["hello ", "world"])
        self.assertEqual(visible, "hello world")
        self.assertEqual(calls, [])


class _FakeSSEResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode()


def _content(text: str) -> bytes:
    return _sse({"choices": [{"delta": {"content": text}}]})


TOOLS = [{
    "type": "function",
    "function": {"name": "get_weather", "parameters": {"type": "object"}},
}]


def _run_stream(lines, **kwargs):
    """Drive streaming.stream() against canned SSE lines; returns the
    consumed StreamingResponse and the payload that was posted."""
    fake = _FakeSSEResponse(lines + [b"data: [DONE]"])
    with mock.patch.object(streaming.requests, "post", return_value=fake) as post:
        response = streaming.stream(
            base_url="http://localhost:1234",
            model="local-model",
            user_message="hi",
            backend="lmstudio",
            **kwargs,
        )
        response.consume()
        payload = post.call_args.kwargs.get("json") or post.call_args[1]["json"]
    return response, payload


class TestToolsPassthrough(unittest.TestCase):
    def test_tools_forwarded_in_payload(self):
        _response, payload = _run_stream([_content("hi")], tools=TOOLS, tool_choice="auto")
        self.assertEqual(payload["tools"], TOOLS)
        self.assertEqual(payload["tool_choice"], "auto")

    def test_no_tools_means_no_payload_keys(self):
        _response, payload = _run_stream([_content("hi")])
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)

    def test_hermes_text_call_extracted_when_tools_given(self):
        response, _payload = _run_stream(
            [
                _content("Sure. "),
                _content('<tool_call>{"name": "get_weather", '),
                _content('"arguments": {"city": "Paris"}}</tool_call>'),
                _content(" Done."),
            ],
            tools=TOOLS,
        )
        self.assertEqual(response.text, "Sure.  Done.")
        self.assertEqual(response.tool_calls, [
            {"id": None, "name": "get_weather", "arguments": {"city": "Paris"}}
        ])

    def test_tags_pass_through_without_tools(self):
        response, _payload = _run_stream(
            [_content('see <tool_call>{"name": "x"}</tool_call>')],
        )
        self.assertIn("<tool_call>", response.text)
        self.assertEqual(response.tool_calls, [])

    def test_native_delta_tool_calls_accumulate(self):
        lines = [
            _sse({"choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "call_1",
                "function": {"name": "get_weather", "arguments": ""},
            }]}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": '{"city": '},
            }]}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": '"Paris"}'},
            }]}}]}),
        ]
        response, _payload = _run_stream(lines, tools=TOOLS)
        self.assertEqual(response.text, "")
        self.assertEqual(response.tool_calls, [
            {"id": "call_1", "name": "get_weather", "arguments": {"city": "Paris"}}
        ])

    def test_anthropic_rejects_tools_for_now(self):
        with self.assertRaises(ValueError):
            list(streaming.stream_completion(
                base_url="https://api.anthropic.com",
                model="claude-sonnet-5",
                user_message="hi",
                backend="anthropic",
                api_key="k",
                tools=TOOLS,
            ))


class TestStreamingResponse(unittest.TestCase):
    def test_text_accumulates_during_iteration(self):
        response = StreamingResponse(iter(["a", "", "b"]), {}, {}, [])
        seen = list(response)
        self.assertEqual(seen, ["a", "", "b"])
        self.assertEqual(response.text, "ab")

    def test_usage_and_reasoning_views(self):
        usage, reasoning = {}, {}
        response = StreamingResponse(iter(["x"]), usage, reasoning, [])
        response.consume()
        usage["input_tokens"] = 3
        reasoning["text"] = "hmm"
        self.assertEqual(response.usage, {"input_tokens": 3})
        self.assertEqual(response.reasoning, "hmm")


if __name__ == "__main__":
    unittest.main()
