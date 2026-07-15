"""Backend registry and URL construction.

Every other module keys its behavior off the backend string. ``lmstudio``,
``ollama``, and ``custom`` speak the OpenAI-compatible HTTP API of a server the
user runs; ``custom`` also reaches OpenAI-compatible *clouds* (DeepSeek, Groq,
Together, OpenRouter, …) when you point ``base_url`` at them and pass an
``api_key``. The named cloud backends (``openai``, ``gemini``) are OpenAI-
compatible too, while ``anthropic`` goes through the official SDK.
"""

DEFAULT_TIMEOUT = 15  # seconds for non-generation requests
GENERATION_TIMEOUT = 900  # 15 minutes for generation

# Default base URLs per backend
BACKEND_DEFAULTS = {
    "lmstudio": "http://localhost:1234",
    "ollama": "http://localhost:11434",
    # llama.cpp server's default port; also covers llama-swap, vLLM, Jan,
    # KoboldCpp, TabbyAPI — anything speaking the OpenAI API. Override base_url
    # (and pass api_key) to reach an OpenAI-compatible *cloud*: DeepSeek, Groq,
    # Together, Fireworks, OpenRouter, Mistral, DeepInfra, ...
    "custom": "http://localhost:8080",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    # Gemini's OpenAI-compatible base already includes the /v1beta/openai path
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

BACKEND_LABELS = {
    "lmstudio": "LM Studio",
    "ollama": "Ollama",
    "custom": "Custom (OpenAI-compatible, local or cloud)",
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "gemini": "Google Gemini",
}

CLOUD_BACKENDS = {"openai", "anthropic", "gemini"}

# Backends whose server exposes load/unload/loaded-model introspection.
# `custom` is deliberately excluded: there is no standardized lifecycle API
# across llama.cpp / vLLM / llama-swap / Jan, so residency is opaque there.
MANAGED_BACKENDS = {"lmstudio", "ollama"}

# Environment variables checked (before any stored key) for each provider
ENV_KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def is_cloud(backend: str) -> bool:
    """True for paid API backends (no local server, no VRAM management)."""
    return backend in CLOUD_BACKENDS


def is_managed(backend: str) -> bool:
    """True when the backend's server supports load/unload/ps introspection."""
    return backend in MANAGED_BACKENDS


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


def auth_headers(backend: str, api_key: str) -> dict:
    """Bearer ``Authorization`` header whenever an API key is provided.

    Covers the named clouds (OpenAI/Gemini) *and* any OpenAI-compatible
    provider reached through the ``custom`` backend — DeepSeek, Groq, Together,
    Fireworks, OpenRouter, Mistral, DeepInfra, an authenticated vLLM, and so
    on. Local servers (LM Studio, Ollama, llama.cpp) normally pass no key, so
    they get no header and are unaffected.
    """
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


# Backwards-compatible alias (pre-library code imported the underscore name)
_auth_headers = auth_headers
