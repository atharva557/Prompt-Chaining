"""Server discovery: connection tests, model listing, readiness polling."""

import time

import requests

from .backends import (
    BACKEND_LABELS,
    DEFAULT_TIMEOUT,
    auth_headers,
    is_cloud,
    models_url,
)


def _anthropic_models(api_key: str) -> tuple[list[str], str]:
    """List Anthropic models via the official SDK (auto-paginates)."""
    try:
        import anthropic
    except ImportError:
        return [], (
            "The 'anthropic' package is required for the Anthropic backend. "
            "Run: pip install anthropic"
        )
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=DEFAULT_TIMEOUT)
        return [m.id for m in client.models.list()], ""
    except anthropic.AuthenticationError:
        return [], "Invalid Anthropic API key."
    except anthropic.APIConnectionError:
        return [], "Cannot reach the Anthropic API. Check your internet connection."
    except Exception as e:
        return [], f"Error fetching models: {e}"


def test_connection(
    base_url: str, backend: str = "lmstudio", api_key: str = ""
) -> tuple[bool, str]:
    """
    Test connection to the LLM server (cloud or local).
    Returns (success: bool, message: str).
    """
    if backend == "anthropic":
        # No bare ping endpoint; listing models doubles as an auth + reach check
        _models, err = _anthropic_models(api_key)
        return (True, "Connected successfully!") if not err else (False, err)

    base_url = base_url.rstrip("/")
    if is_cloud(backend) and not api_key:
        return False, f"An API key is required for {BACKEND_LABELS.get(backend, backend)}."
    try:
        resp = requests.get(
            models_url(base_url, backend),
            headers=auth_headers(backend, api_key),
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 200:
            return True, "Connected successfully!"
        if resp.status_code in (401, 403):
            return False, "Authentication failed — check your API key."
        return False, f"Server returned status {resp.status_code}"
    except requests.ConnectionError:
        return False, f"Cannot connect to {base_url}. Make sure your LLM server is running."
    except requests.Timeout:
        return False, f"Connection to {base_url} timed out."
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def get_models(
    base_url: str, backend: str = "lmstudio", api_key: str = ""
) -> tuple[list[str], str]:
    """
    Fetch available models from the server (cloud or local).
    Returns (model_list, error_message). error_message is empty on success.
    """
    if backend == "anthropic":
        return _anthropic_models(api_key)

    base_url = base_url.rstrip("/")
    if is_cloud(backend) and not api_key:
        return [], f"An API key is required for {BACKEND_LABELS.get(backend, backend)}."
    try:
        resp = requests.get(
            models_url(base_url, backend),
            headers=auth_headers(backend, api_key),
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            if resp.status_code in (401, 403):
                return [], "Authentication failed — check your API key."
            return [], f"Failed to fetch models (status {resp.status_code})"

        data = resp.json()
        if backend == "ollama":
            # Newer Ollama versions use "model", older ones "name"
            models = [
                m.get("model") or m.get("name", "")
                for m in data.get("models", [])
            ]
            return [m for m in models if m], ""
        # OpenAI-compatible (lmstudio, custom, openai, gemini)
        models = [m["id"] for m in data.get("data", [])]
        return models, ""
    except requests.ConnectionError:
        return [], f"Cannot connect to {base_url}. Is your LLM server running?"
    except requests.Timeout:
        return [], "Connection timed out."
    except Exception as e:
        return [], f"Error fetching models: {str(e)}"


def wait_until_ready(
    base_url: str,
    backend: str = "lmstudio",
    api_key: str = "",
    model: str | None = None,
    timeout: float = 60.0,
    interval: float = 1.0,
) -> tuple[bool, str]:
    """
    Poll until the server answers — and, when `model` is given, until that
    model appears in the server's model list. Returns (ready, message);
    on failure the message is the last error observed before the deadline.

    The classic use is gating a script or CI job on "ollama is actually up":
        ok, msg = wait_until_ready("http://localhost:11434", "ollama",
                                   model="qwen3:8b", timeout=120)
    """
    deadline = time.monotonic() + timeout
    last_message = "Timed out before the first check completed."
    while True:
        ok, message = test_connection(base_url, backend, api_key)
        if ok:
            if not model:
                return True, "Server ready."
            names, err = get_models(base_url, backend, api_key)
            if not err and model in names:
                return True, f"Server ready; model '{model}' available."
            last_message = err or (
                f"Server up, but model '{model}' is not in its model list."
            )
        else:
            last_message = message
        if time.monotonic() >= deadline:
            return False, last_message
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())) or interval)
