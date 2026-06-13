import requests
import json
from typing import Optional

DEFAULT_TIMEOUT = 15  # seconds for non-generation requests
GENERATION_TIMEOUT = 900  # 15 minutes for generation

# Default base URLs per backend
BACKEND_DEFAULTS = {
    "lmstudio": "http://localhost:1234",
    "ollama": "http://localhost:11434",
    # llama.cpp server's default port; also covers llama-swap, vLLM, Jan,
    # KoboldCpp, TabbyAPI — anything speaking the OpenAI API
    "custom": "http://localhost:8080",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    # Gemini's OpenAI-compatible base already includes the /v1beta/openai path
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

BACKEND_LABELS = {
    "lmstudio": "LM Studio",
    "ollama": "Ollama",
    "custom": "Custom (OpenAI-compatible)",
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "gemini": "Google Gemini",
}

CLOUD_BACKENDS = {"openai", "anthropic", "gemini"}

# Environment variables checked (before config.json) for each provider's key
ENV_KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def is_cloud(backend: str) -> bool:
    """True for paid API backends (no local server, no VRAM management)."""
    return backend in CLOUD_BACKENDS


def chat_completions_url(base_url: str, backend: str) -> str:
    """Chat-completions endpoint for a backend (Anthropic excluded — it
    goes through the official SDK, not an OpenAI-compatible path)."""
    base_url = base_url.rstrip("/")
    if backend == "gemini":
        # base already ends in /v1beta/openai
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def models_url(base_url: str, backend: str) -> str:
    """Model-listing endpoint for a backend."""
    base_url = base_url.rstrip("/")
    if backend == "ollama":
        return f"{base_url}/api/tags"
    if backend == "gemini":
        return f"{base_url}/models"
    return f"{base_url}/v1/models"


def _auth_headers(backend: str, api_key: str) -> dict:
    if api_key and is_cloud(backend):
        return {"Authorization": f"Bearer {api_key}"}
    return {}


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


def test_connection(base_url: str, backend: str = "lmstudio") -> tuple[bool, str]:
    """
    Test connection to the LLM server.
    Returns (success: bool, message: str).
    """
    base_url = base_url.rstrip("/")
    try:
        if backend == "ollama":
            resp = requests.get(f"{base_url}/api/tags", timeout=DEFAULT_TIMEOUT)
        else:
            resp = requests.get(f"{base_url}/v1/models", timeout=DEFAULT_TIMEOUT)
        
        if resp.status_code == 200:
            return True, "Connected successfully!"
        else:
            return False, f"Server returned status {resp.status_code}"
    except requests.ConnectionError:
        return False, f"Cannot connect to {base_url}. Make sure your LLM server is running."
    except requests.Timeout:
        return False, f"Connection to {base_url} timed out."
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def get_models(base_url: str, backend: str = "lmstudio") -> tuple[list[str], str]:
    """
    Fetch available models from the server.
    Returns (model_list, error_message). error_message is empty on success.
    """
    base_url = base_url.rstrip("/")
    try:
        if backend == "ollama":
            resp = requests.get(f"{base_url}/api/tags", timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                # Newer Ollama versions use "model", older ones "name"
                models = [
                    m.get("model") or m.get("name", "")
                    for m in data.get("models", [])
                ]
                models = [m for m in models if m]
                return models, ""
            else:
                return [], f"Failed to fetch models (status {resp.status_code})"
        else:
            # LM Studio uses OpenAI-compatible endpoint
            resp = requests.get(f"{base_url}/v1/models", timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                return models, ""
            else:
                return [], f"Failed to fetch models (status {resp.status_code})"
    except requests.ConnectionError:
        return [], f"Cannot connect to {base_url}. Is your LLM server running?"
    except requests.Timeout:
        return [], f"Connection timed out."
    except Exception as e:
        return [], f"Error fetching models: {str(e)}"


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
    Generate a non-streaming completion.
    Both LM Studio and Ollama support the OpenAI-compatible /v1/chat/completions endpoint.
    Returns (response_text, error_message). error_message is empty on success.

    Currently unused by the app (streaming is used everywhere) — kept as a
    non-streaming fallback.
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
            timeout=GENERATION_TIMEOUT
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


def unload_model(base_url: str, model_id: str, backend: str = "lmstudio") -> bool:
    """
    Best-effort model unload. Never raises exceptions.
    LM Studio: native /api/v1/models/unload (0.4.0+), TTL=0 trick as fallback.
    Ollama: uses keep_alive=0 parameter.
    Custom: no-op — there is no standardized unload across OpenAI-compatible
    servers, and the TTL trick would *load* the model on llama-swap. Eviction
    is left to the server's own policy.
    Returns True if unload was attempted (not guaranteed to work).
    """
    base_url = base_url.rstrip("/")
    if backend == "custom":
        return False
    try:
        if backend == "ollama":
            # Ollama: POST /api/generate with keep_alive=0
            payload = {
                "model": model_id,
                "prompt": "",
                "keep_alive": 0
            }
            requests.post(
                f"{base_url}/api/generate",
                json=payload,
                timeout=DEFAULT_TIMEOUT
            )
            return True

        # LM Studio 0.4.0+: native unload endpoint. Unlike the TTL trick,
        # this never loads the model first.
        try:
            resp = requests.post(
                f"{base_url}/api/v1/models/unload",
                json={"instance_id": model_id},
                timeout=DEFAULT_TIMEOUT
            )
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass

        # Fallback for older LM Studio: TTL=0 trick via chat completions.
        # Caveat: if the model was already evicted, this reloads it just to
        # unload it — that's why the native endpoint above is preferred.
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": ""}],
            "max_tokens": 1,
            "ttl": 0
        }
        requests.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            timeout=DEFAULT_TIMEOUT
        )
        return True
    except Exception:
        return False  # Best-effort, don't crash
