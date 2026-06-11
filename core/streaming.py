"""
PromptChain — Streaming Module

Handles real-time token streaming from LLM servers via Server-Sent Events (SSE).
Both LM Studio and Ollama support the OpenAI-compatible streaming format.
"""

import json
import requests
from typing import Generator

# Default timeouts per role
PROMPTER_TIMEOUT = 180   # 3 minutes for small/fast prompter models
CODER_TIMEOUT = 900      # 15 minutes for larger coder models


def stream_completion(
    base_url: str,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    backend: str = "lmstudio",
    timeout: int = CODER_TIMEOUT,
) -> Generator[str, None, None]:
    """
    Generator that yields text tokens as they arrive via SSE streaming.

    Uses the OpenAI-compatible /v1/chat/completions endpoint with stream=True.
    Both LM Studio and Ollama support this format.

    Yields:
        str: Individual text tokens as they arrive.

    Raises:
        ConnectionError: If the server is unreachable.
        TimeoutError: If the request times out.
        RuntimeError: If the server returns an error status.
    """
    base_url = base_url.rstrip("/")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
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
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    yield token
            except (json.JSONDecodeError, KeyError, IndexError):
                # Skip malformed chunks silently
                continue

    except requests.ConnectionError:
        raise ConnectionError(
            f"Lost connection to {base_url}. Is your LLM server still running?"
        )
    except requests.Timeout:
        raise TimeoutError(
            "Generation timed out. The model may be overloaded or the prompt too long."
        )
