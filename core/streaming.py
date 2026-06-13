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
) -> Generator[str, None, None]:
    """
    Generator that yields text tokens as they arrive.

    Pass either system_prompt + user_message (single-turn), or a full
    `messages` list for multi-turn conversations (chat, code refinement);
    `messages` takes precedence when provided.

    If `usage_out` is provided, it is populated with {"input_tokens",
    "output_tokens"} once the backend reports usage (cloud backends only).

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
            backend, timeout, api_key, usage_out,
        )


def _stream_openai_compatible(
    base_url, model, messages, temperature, max_tokens,
    backend, timeout, api_key, usage_out,
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
                token = choices[0].get("delta", {}).get("content", "")
                if token:
                    yield token

    except requests.ConnectionError:
        raise ConnectionError(
            f"Lost connection to {base_url}. Is your LLM server still running?"
        )
    except requests.Timeout:
        raise TimeoutError(
            "Generation timed out. The model may be overloaded or the prompt too long."
        )


def _anthropic_omits_temperature(model: str) -> bool:
    """Opus 4.7+, 4.8, and Fable models reject sampling params (400)."""
    m = model.lower()
    return m.startswith(("claude-opus-4-7", "claude-opus-4-8", "claude-fable"))


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
    if not _anthropic_omits_temperature(model):
        kwargs["temperature"] = temperature

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
            if usage_out is not None:
                usage = stream.get_final_message().usage
                usage_out["input_tokens"] = usage.input_tokens
                usage_out["output_tokens"] = usage.output_tokens
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
