"""Real-time token streaming from LLM backends.

Local servers (LM Studio, Ollama, llama.cpp, …) and OpenAI-compatible clouds
(OpenAI, Gemini) stream via Server-Sent Events on the /chat/completions
endpoint; Anthropic streams through its own SDK.

Two stream filters keep non-answer content out of the visible token stream:

* :class:`ThinkTagFilter` strips a *leading* ``<think>…</think>`` reasoning
  block (DeepSeek-R1 / Qwen3 / GLM style).
* :class:`ToolCallFilter` extracts Hermes-format ``<tool_call>{…}</tool_call>``
  blocks — the de-facto function-calling format of local models — for servers
  that don't parse tool calls themselves.

:func:`stream` is the high-level entry point returning a
:class:`StreamingResponse`; :func:`stream_completion` is the raw generator
underneath it.
"""

import json
from typing import Generator

import requests

from .backends import (
    auth_headers,
    chat_completions_url,
    is_cloud,
)
from .errors import (
    AuthenticationError,
    BackendConnectionError,
    BackendResponseError,
    GenerationTimeout,
)

# Default timeout for a streamed generation (big local models can be slow)
DEFAULT_STREAM_TIMEOUT = 900


def _partial_suffix_len(buf: str, tag: str) -> int:
    """Length of the longest strict prefix of `tag` that `buf` ends with —
    i.e. how many trailing chars might be the start of a tag split across
    chunk boundaries and must stay buffered."""
    for k in range(min(len(tag) - 1, len(buf)), 0, -1):
        if buf.endswith(tag[:k]):
            return k
    return 0


class ThinkTagFilter:
    """Incrementally strips a leading ``<think> … </think>`` reasoning block
    (as emitted by DeepSeek-R1 / Qwen3 / GLM-style models) from streamed text.

    Only a block that *opens* the output (after optional whitespace) is treated
    as reasoning, so a literal ``<think>`` later in real output passes through
    untouched. Tags split across chunk boundaries are handled by buffering.
    The hidden reasoning accumulates in ``.reasoning``; call ``flush()`` once
    the stream ends to release any still-buffered text.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self):
        self.reasoning = ""
        self._buf = ""
        # 'start' → deciding whether the output opens with <think>;
        # 'think' → inside the block; 'lead' → skipping whitespace after it;
        # 'pass'  → verbatim passthrough for the rest of the stream.
        self._state = "start"

    def feed(self, text: str) -> str:
        """Consume one streamed chunk, return the visible part (may be '')."""
        if self._state == "pass":
            return text
        self._buf += text
        if self._state == "start":
            stripped = self._buf.lstrip()
            if not stripped:
                return ""  # only whitespace so far — keep waiting
            if len(stripped) < len(self.OPEN) and self.OPEN.startswith(stripped):
                return ""  # could still become '<think>' — keep buffering
            if stripped.startswith(self.OPEN):
                self._state = "think"
                self._buf = stripped[len(self.OPEN):]
            else:
                out, self._buf = self._buf, ""
                self._state = "pass"
                return out
        if self._state == "think":
            idx = self._buf.find(self.CLOSE)
            if idx < 0:
                # keep a possible partial '</think>' buffered for the next chunk
                keep = _partial_suffix_len(self._buf, self.CLOSE)
                cut = len(self._buf) - keep
                self.reasoning += self._buf[:cut]
                self._buf = self._buf[cut:]
                return ""
            self.reasoning += self._buf[:idx]
            self._buf = self._buf[idx + len(self.CLOSE):]
            self._state = "lead"
        if self._state == "lead":
            visible = self._buf.lstrip()
            self._buf = ""
            if visible:
                self._state = "pass"
            return visible
        return ""

    def flush(self) -> str:
        """Stream ended: return any buffered text that never became a tag.
        An unterminated think block counts entirely as reasoning."""
        out, self._buf = self._buf, ""
        if self._state == "think":
            self.reasoning += out
            out = ""
        self._state = "pass"
        return out


class ToolCallFilter:
    """Incrementally extracts Hermes-format tool calls from streamed text.

    Hermes-style models (NousResearch Hermes, Qwen, and most local models
    tuned for function calling) emit calls inline as::

        <tool_call>
        {"name": "get_weather", "arguments": {"city": "Paris"}}
        </tool_call>

    Servers with a tool parser (vLLM ``--tool-call-parser hermes``, llama.cpp
    ``--jinja``, Ollama) surface these as structured deltas and this filter
    never sees them; for everything else (plain LM Studio / llama.cpp), the
    tags arrive as ordinary text and would leak into the visible output.

    ``feed()`` returns the visible portion of each chunk with any complete
    ``<tool_call>`` blocks removed; parsed calls accumulate in
    ``.tool_calls`` as ``{"id", "name", "arguments"}`` dicts (``arguments``
    stays a raw string when the payload isn't valid JSON). Unlike
    :class:`ThinkTagFilter`, blocks may appear anywhere in the output and
    repeat. Tags split across chunk boundaries are buffered.
    """

    OPEN = "<tool_call>"
    CLOSE = "</tool_call>"

    def __init__(self):
        self.tool_calls: list[dict] = []
        self._buf = ""
        self._in_call = False

    def feed(self, text: str) -> str:
        """Consume one streamed chunk, return the visible part (may be '')."""
        self._buf += text
        visible: list[str] = []
        while True:
            if not self._in_call:
                idx = self._buf.find(self.OPEN)
                if idx >= 0:
                    visible.append(self._buf[:idx])
                    self._buf = self._buf[idx + len(self.OPEN):]
                    self._in_call = True
                    continue
                # emit everything except a trailing partial '<tool_call'
                keep = _partial_suffix_len(self._buf, self.OPEN)
                cut = len(self._buf) - keep
                visible.append(self._buf[:cut])
                self._buf = self._buf[cut:]
                return "".join(visible)
            idx = self._buf.find(self.CLOSE)
            if idx >= 0:
                self._record(self._buf[:idx])
                self._buf = self._buf[idx + len(self.CLOSE):]
                self._in_call = False
                continue
            # still inside the call — keep buffering the whole payload
            return "".join(visible)

    def _record(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        try:
            obj = json.loads(raw)
            self.tool_calls.append({
                "id": obj.get("id"),
                "name": obj.get("name", ""),
                "arguments": obj.get("arguments", {}),
            })
        except (json.JSONDecodeError, AttributeError):
            # Malformed payload: surface it raw rather than dropping it
            self.tool_calls.append({"id": None, "name": "", "arguments": raw})

    def flush(self) -> str:
        """Stream ended: release buffered text. An unterminated tool call is
        still recorded (salvaged) rather than silently dropped."""
        out, self._buf = self._buf, ""
        if self._in_call:
            self._record(out)
            out = ""
            self._in_call = False
        return out


class StreamingResponse:
    """Iterable handle over a streamed generation.

    Iterate it for live tokens (empty strings mark reasoning/tool-call-only
    chunks — UI progress ticks); after (or during) iteration:

    * ``.text`` — visible output accumulated so far
    * ``.reasoning`` — hidden model reasoning collected so far
    * ``.usage`` — ``{"input_tokens", "output_tokens"}`` once reported
    * ``.tool_calls`` — parsed tool calls (Hermes-format text and/or
      OpenAI-native structured deltas)

    ``consume()`` drains the stream and returns the full text in one call.
    """

    def __init__(self, generator, usage: dict, reasoning: dict,
                 tool_calls: list, model: str = ""):
        self._gen = generator
        self._usage = usage
        self._reasoning = reasoning
        self.tool_calls = tool_calls
        self.model = model
        self.text = ""

    def __iter__(self):
        for token in self._gen:
            if token:
                self.text += token
            yield token

    @property
    def usage(self) -> dict:
        return dict(self._usage)

    @property
    def reasoning(self) -> str:
        return self._reasoning.get("text", "")

    def consume(self) -> str:
        """Drain the stream and return the complete visible text."""
        for _ in self:
            pass
        return self.text


def stream(
    base_url: str,
    model: str,
    system_prompt: str = "",
    user_message: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1024,
    backend: str = "lmstudio",
    timeout: int = DEFAULT_STREAM_TIMEOUT,
    messages: list[dict] | None = None,
    api_key: str = "",
    tools: list[dict] | None = None,
    tool_choice=None,
    parse_tool_calls: bool | None = None,
) -> StreamingResponse:
    """High-level streaming call returning a :class:`StreamingResponse`.

    Same parameters as :func:`stream_completion`, minus the mutable out-dicts
    (the response object owns them). ``parse_tool_calls`` controls the
    Hermes-format text filter: None (default) enables it exactly when
    ``tools`` were passed.
    """
    usage: dict = {}
    reasoning: dict = {}
    tool_calls: list = []
    if parse_tool_calls is None:
        parse_tool_calls = tools is not None
    generator = stream_completion(
        base_url=base_url,
        model=model,
        system_prompt=system_prompt,
        user_message=user_message,
        temperature=temperature,
        max_tokens=max_tokens,
        backend=backend,
        timeout=timeout,
        messages=messages,
        api_key=api_key,
        usage_out=usage,
        reasoning_out=reasoning,
        tools=tools,
        tool_choice=tool_choice,
        tool_calls_out=tool_calls if (parse_tool_calls or tools is not None) else None,
        parse_tool_calls=parse_tool_calls,
    )
    return StreamingResponse(generator, usage, reasoning, tool_calls, model)


def stream_completion(
    base_url: str,
    model: str,
    system_prompt: str = "",
    user_message: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1024,
    backend: str = "lmstudio",
    timeout: int = DEFAULT_STREAM_TIMEOUT,
    messages: list[dict] | None = None,
    api_key: str = "",
    usage_out: dict | None = None,
    reasoning_out: dict | None = None,
    tools: list[dict] | None = None,
    tool_choice=None,
    tool_calls_out: list | None = None,
    parse_tool_calls: bool | None = None,
) -> Generator[str, None, None]:
    """
    Generator that yields text tokens as they arrive.

    Pass either system_prompt + user_message (single-turn), or a full
    `messages` list for multi-turn conversations (chat, code refinement);
    `messages` takes precedence when provided.

    If `usage_out` is provided, it is populated with {"input_tokens",
    "output_tokens"} once the backend reports usage (cloud backends only).

    If `reasoning_out` is provided, hidden model reasoning (inline
    ``<think>`` blocks or a ``reasoning_content`` delta field) accumulates
    live under its "text" key instead of being yielded; the generator yields
    an empty string on reasoning-only chunks so the UI can show progress.

    `tools` (OpenAI function-tool dicts) are forwarded to servers that parse
    tool calls natively; structured tool-call deltas — and, when
    `parse_tool_calls` is enabled (default: exactly when `tools` is given),
    raw Hermes-format ``<tool_call>`` text blocks — accumulate in
    `tool_calls_out` instead of the visible stream. Not yet supported on the
    `anthropic` backend.

    Yields:
        str: Individual text tokens as they arrive.

    Raises:
        BackendConnectionError (a ConnectionError): server unreachable.
        GenerationTimeout (a TimeoutError): request timed out.
        BackendResponseError (a RuntimeError): server returned an error.
    """
    if messages is None:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    if backend == "anthropic":
        if tools:
            raise ValueError(
                "tools= is not yet supported on the anthropic backend "
                "(planned; use an OpenAI-compatible backend for tool calling)."
            )
        yield from _stream_anthropic(
            model, messages, temperature, max_tokens, timeout, api_key, usage_out
        )
    else:
        yield from _stream_openai_compatible(
            base_url, model, messages, temperature, max_tokens,
            backend, timeout, api_key, usage_out, reasoning_out,
            tools, tool_choice, tool_calls_out, parse_tool_calls,
        )


def _finalize_native_tool_calls(pending: dict, tool_calls_out: list) -> None:
    """Convert accumulated OpenAI-style tool-call deltas into the same
    {"id", "name", "arguments"} shape ToolCallFilter produces."""
    for idx in sorted(pending):
        entry = pending[idx]
        arguments = entry["arguments"]
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            pass  # leave as the raw string
        tool_calls_out.append({
            "id": entry["id"],
            "name": entry["name"],
            "arguments": arguments,
        })


def _stream_openai_compatible(
    base_url, model, messages, temperature, max_tokens,
    backend, timeout, api_key, usage_out, reasoning_out=None,
    tools=None, tool_choice=None, tool_calls_out=None, parse_tool_calls=None,
) -> Generator[str, None, None]:
    """SSE streaming for local servers and OpenAI/Gemini clouds."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    # Newer OpenAI models reject `max_tokens` in favor of `max_completion_tokens`
    if backend == "openai":
        payload["max_completion_tokens"] = max_tokens
    else:
        payload["max_tokens"] = max_tokens
    # Metered backends report token usage in a trailing chunk when asked: the
    # named clouds, plus any keyed OpenAI-compatible provider via `custom`
    # (DeepSeek, Groq, ...). Local keyless servers skip it — some minimal
    # servers choke on stream_options.
    if is_cloud(backend) or api_key:
        payload["stream_options"] = {"include_usage": True}
    if tools:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

    headers = {"Content-Type": "application/json", **auth_headers(backend, api_key)}

    # Reasoning models hide their thinking either inline (<think> tags in
    # content) or in a separate delta field; both are collected here and kept
    # out of the visible token stream.
    think_filter = ThinkTagFilter()
    field_reasoning = ""

    # Tool calls arrive either as structured deltas (servers with a parser)
    # or as raw Hermes <tool_call> tags in the content text; both funnel into
    # tool_calls_out when the caller asked for them.
    if parse_tool_calls is None:
        parse_tool_calls = tools is not None and tool_calls_out is not None
    tool_filter = ToolCallFilter() if (parse_tool_calls and tool_calls_out is not None) else None
    native_calls: dict = {}

    def _sync_reasoning():
        if reasoning_out is not None:
            combined = field_reasoning + think_filter.reasoning
            if combined:
                reasoning_out["text"] = combined

    def _sync_tool_calls():
        if tool_filter is not None and tool_calls_out is not None:
            del tool_calls_out[: len(tool_calls_out)]
            tool_calls_out.extend(tool_filter.tool_calls)

    try:
        response = requests.post(
            chat_completions_url(base_url, backend),
            headers=headers,
            json=payload,
            stream=True,
            timeout=timeout,
        )

        if response.status_code != 200:
            raise BackendResponseError(
                f"Server returned status {response.status_code}: "
                f"{response.text[:200]}",
                status=response.status_code,
                body=response.text[:2000],
            )

        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode("utf-8")

            # SSE format: "data: {...}" or "data: [DONE]"
            if not line_str.startswith("data: "):
                continue

            data = line_str[6:]  # Strip "data: " prefix

            if data.strip() == "[DONE]":
                break

            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue  # Skip malformed chunks silently

            # The usage-bearing chunk (cloud, include_usage) has empty choices
            usage = chunk.get("usage")
            if usage and usage_out is not None:
                usage_out["input_tokens"] = usage.get("prompt_tokens")
                usage_out["output_tokens"] = usage.get("completion_tokens")

            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                # DeepSeek-style servers stream thinking in a separate field
                # (`reasoning_content`; OpenRouter uses `reasoning`)
                thinking = delta.get("reasoning_content") or delta.get("reasoning")
                if thinking:
                    field_reasoning += thinking
                    _sync_reasoning()
                    yield ""  # no visible text, but let the UI show progress

                # Structured tool-call deltas (server-side tool parser):
                # fragments accumulate per index until the stream ends.
                delta_calls = delta.get("tool_calls")
                if delta_calls and tool_calls_out is not None:
                    for frag in delta_calls:
                        idx = frag.get("index", 0)
                        entry = native_calls.setdefault(
                            idx, {"id": None, "name": "", "arguments": ""}
                        )
                        if frag.get("id"):
                            entry["id"] = frag["id"]
                        fn = frag.get("function") or {}
                        if fn.get("name"):
                            entry["name"] = fn["name"]
                        if fn.get("arguments"):
                            entry["arguments"] += fn["arguments"]
                    yield ""  # progress tick, nothing visible

                token = delta.get("content", "")
                if token:
                    hidden_before = len(think_filter.reasoning)
                    visible = think_filter.feed(token)
                    reasoned = len(think_filter.reasoning) > hidden_before
                    if reasoned:
                        _sync_reasoning()
                    if visible and tool_filter is not None:
                        calls_before = len(tool_filter.tool_calls)
                        visible = tool_filter.feed(visible)
                        if len(tool_filter.tool_calls) > calls_before:
                            _sync_tool_calls()
                            if not visible:
                                yield ""  # tool-call-only chunk: progress tick
                    if visible:
                        yield visible
                    elif reasoned:
                        yield ""

        # Release anything the filters still hold (e.g. text that looked
        # like a partial tag but never completed it)
        tail = think_filter.flush()
        if tool_filter is not None:
            tail = tool_filter.feed(tail) if tail else tail
            tail = (tail or "") + tool_filter.flush()
            _sync_tool_calls()
        if tail:
            yield tail
        if tool_calls_out is not None and native_calls:
            _finalize_native_tool_calls(native_calls, tool_calls_out)

    except requests.ConnectionError:
        raise BackendConnectionError(
            f"Lost connection to {base_url}. Is your LLM server still running?"
        )
    except requests.Timeout:
        raise GenerationTimeout(
            "Generation timed out. The model may be overloaded or the prompt too long."
        )


def generate_completion(
    base_url: str,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    backend: str = "lmstudio"
) -> tuple[str, str]:
    """
    Generate a non-streaming completion against an OpenAI-compatible server.
    Returns (response_text, error_message). error_message is empty on success.

    Kept as a non-streaming fallback; streaming is used everywhere else.
    """
    base_url = base_url.rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=DEFAULT_STREAM_TIMEOUT
        )

        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip(), ""
        else:
            return "", f"Generation failed (status {resp.status_code}): {resp.text[:200]}"
    except requests.Timeout:
        return "", "Generation timed out. The model may be too slow or the prompt too long."
    except requests.ConnectionError:
        return "", "Lost connection to the server during generation."
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        return "", f"Failed to parse response: {str(e)}"
    except Exception as e:
        return "", f"Unexpected error during generation: {str(e)}"


def _anthropic_omits_temperature(model: str) -> bool:
    """Known models that reject sampling params (`temperature`/`top_p`/`top_k`)
    with a 400: Opus 4.7/4.8 and the Fable family. This is only a *fast path*
    that skips a wasted first request for current models — `_stream_anthropic`
    also retries without sampling params on any 400 that complains about them,
    so a future model not listed here still works (it just pays one rejected
    request). Keep the list accurate, but correctness no longer depends on it."""
    m = model.lower()
    return m.startswith(("claude-opus-4-7", "claude-opus-4-8", "claude-fable"))


def _is_sampling_param_error(err) -> bool:
    """True when a 400 looks like the API rejecting a sampling parameter, so the
    request can be retried without it."""
    msg = (getattr(err, "message", "") or str(err)).lower()
    return any(p in msg for p in ("temperature", "top_p", "top_k", "sampling"))


def _stream_anthropic(
    model, messages, temperature, max_tokens, timeout, api_key, usage_out,
) -> Generator[str, None, None]:
    """Streaming via the official Anthropic SDK. The system prompt is a
    top-level param, so any system messages are extracted from `messages`."""
    try:
        import anthropic
    except ImportError:
        raise BackendResponseError(
            "The 'anthropic' package is required for the Anthropic backend. "
            "Run: pip install anthropic"
        )

    system = "\n\n".join(
        m["content"] for m in messages if m.get("role") == "system" and m.get("content")
    )
    convo = [m for m in messages if m.get("role") != "system"]

    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": convo,
    }
    if system:
        kwargs["system"] = system
    # Fast path: skip temperature for models known to reject sampling params.
    if not _anthropic_omits_temperature(model):
        kwargs["temperature"] = temperature

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def _attempt(call_kwargs):
        with client.messages.stream(**call_kwargs) as stream_ctx:
            for text in stream_ctx.text_stream:
                yield text
            if usage_out is not None:
                usage = stream_ctx.get_final_message().usage
                usage_out["input_tokens"] = usage.input_tokens
                usage_out["output_tokens"] = usage.output_tokens

    try:
        # Forward-compat net: a model not in the fast-path list above may still
        # reject `temperature` with a 400. If that happens before any token has
        # streamed, drop the param and retry once. BadRequestError is a subclass
        # of APIStatusError, so it must be handled before the generic mapping.
        emitted = False
        try:
            for text in _attempt(kwargs):
                emitted = True
                yield text
        except anthropic.BadRequestError as e:
            if not emitted and "temperature" in kwargs and _is_sampling_param_error(e):
                kwargs.pop("temperature", None)
                yield from _attempt(kwargs)
            else:
                raise
    except anthropic.APITimeoutError:
        raise GenerationTimeout(
            "Generation timed out. The model may be overloaded or the prompt too long."
        )
    except anthropic.APIConnectionError:
        raise BackendConnectionError(
            "Lost connection to the Anthropic API. Check your internet connection."
        )
    except anthropic.AuthenticationError:
        raise AuthenticationError("Anthropic authentication failed — check your API key.")
    except anthropic.APIStatusError as e:
        raise BackendResponseError(
            f"Anthropic API error ({e.status_code}): {e.message}",
            status=e.status_code,
        )
