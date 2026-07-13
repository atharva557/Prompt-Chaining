"""The Endpoint dataclass — where a model lives and how to reach it."""

import os
from dataclasses import dataclass, field

from .backends import (
    BACKEND_DEFAULTS,
    ENV_KEY_NAMES,
    is_cloud,
    is_managed,
)
from .costs import parse_size


@dataclass
class Endpoint:
    """One reachable model: backend + server + model id (+ credentials).

    ``base_url`` defaults to the backend's conventional local/cloud URL and
    ``api_key`` falls back to the provider's environment variable
    (OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY), so the common cases
    are just ``Endpoint("ollama", "qwen3:8b")`` or
    ``Endpoint("anthropic", "claude-sonnet-5")``.

    ``vram_hint`` (e.g. ``"18GiB"``) feeds ModelManager's vram_budget for
    servers that don't report model sizes themselves.
    """

    backend: str
    model: str = ""
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    vram_hint: str | int | None = None

    def __post_init__(self):
        if self.backend not in BACKEND_DEFAULTS:
            raise ValueError(
                f"Unknown backend '{self.backend}'. "
                f"Expected one of: {', '.join(sorted(BACKEND_DEFAULTS))}"
            )
        if not self.base_url:
            self.base_url = BACKEND_DEFAULTS[self.backend]
        self.base_url = self.base_url.rstrip("/")
        if not self.api_key and is_cloud(self.backend):
            env_name = ENV_KEY_NAMES.get(self.backend)
            if env_name:
                self.api_key = os.environ.get(env_name, "").strip()

    @property
    def is_local(self) -> bool:
        """True for backends running on the user's own hardware."""
        return not is_cloud(self.backend)

    @property
    def is_managed(self) -> bool:
        """True when the server supports load/unload/loaded-model APIs
        (LM Studio, Ollama) — i.e. residency can actually be managed."""
        return is_managed(self.backend)

    @property
    def vram_bytes(self) -> int | None:
        """The vram_hint parsed to bytes, or None when not provided."""
        return parse_size(self.vram_hint)
