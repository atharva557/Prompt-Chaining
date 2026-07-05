"""
PromptChain — Streaming Module

Handles real-time token streaming from LLM backends. Local servers (LM Studio,
Ollama) and OpenAI-compatible clouds (OpenAI, Gemini) stream via Server-Sent
Events on the /chat/completions endpoint; Anthropic streams through its own SDK.
"""

import json
import requests
from typing import Generator

from core.api import (
    chat_completions_url,
    is_cloud,
    _auth_headers,
)

# Default timeouts per role
PROMPTER_TIMEOUT = 180   # 3 minutes for small/fast prompter models
CODER_TIMEOUT = 900      # 15 minutes for larger coder models


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


def stream_completion(
    base_url: str,
    model: str,
    system_prompt: str = "",
    user_message: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1024,
    backend: str = "lmstudio",
    timeout: int = CODER_TIMEOUT,
    messages: list[dict] | None = None,
    api_key: str = "",
    usage_out: dict | None = None,
    reasoning_out: dict | None = None,
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

    Yields:
        str: Individual text tokens as they arrive.

    Raises:
        ConnectionError: If the server is unreachable.
        TimeoutError: If the request times out.
        RuntimeError: If the server returns an error status.
    """
    if messages is None:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    if backend == "anthropic":
        yield from _stream_anthropic(
            model, messages, temperature, max_tokens, timeout, api_key, usage_out
        )
    else:
        yield from _stream_openai_compatible(
            base_url, model, messages, temperature, max_tokens,
            backend, timeout, api_key, usage_out, reasoning_out,
        )


def _stream_openai_compatible(
    base_url, model, messages, temperature, max_tokens,
    backend, timeout, api_key, usage_out, reasoning_out=None,
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
    # Cloud backends report token usage in a trailing chunk when asked
    if is_cloud(backend):
        payload["stream_options"] = {"include_usage": True}

    headers = {"Content-Type": "application/json", **_auth_headers(backend, api_key)}

    # Reasoning models hide their thinking either inline (<think> tags in
    # content) or in a separate delta field; both are collected here and kept
    # out of the visible token stream.
    think_filter = ThinkTagFilter()
    field_reasoning = ""

    def _sync_reasoning():
        if reasoning_out is not None:
            combined = field_reasoning + think_filter.reasoning
            if combined:
                reasoning_out["text"] = combined

    try:
        response = requests.post(
            chat_completions_url(base_url, backend),
            headers=headers,
            json=payload,
            stream=True,
            timeout=timeout,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Server returned status {response.status_code}: "
                f"{response.text[:200]}"
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
                token = delta.get("content", "")
                if token:
                    hidden_before = len(think_filter.reasoning)
                    visible = think_filter.feed(token)
                    reasoned = len(think_filter.reasoning) > hidden_before
                    if reasoned:
                        _sync_reasoning()
                    if visible:
                        yield visible
                    elif reasoned:
                        yield ""

        # Release anything the filter still holds (e.g. text that looked
        # like a partial '<think>' but never completed the tag)
        tail = think_filter.flush()
        if tail:
            yield tail

    except requests.ConnectionError:
        raise ConnectionError(
            f"Lost connection to {base_url}. Is your LLM server still running?"
        )
    except requests.Timeout:
        raise TimeoutError(
            "Generation timed out. The model may be overloaded or the prompt too long."
        )


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
        raise RuntimeError(
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
        with client.messages.stream(**call_kwargs) as stream:
            for text in stream.text_stream:
                yield text
            if usage_out is not None:
                usage = stream.get_final_message().usage
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
        raise TimeoutError(
            "Generation timed out. The model may be overloaded or the prompt too long."
        )
    except anthropic.APIConnectionError:
        raise ConnectionError(
            "Lost connection to the Anthropic API. Check your internet connection."
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("Anthropic authentication failed — check your API key.")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}")
