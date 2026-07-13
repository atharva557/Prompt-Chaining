"""promptchain — load, unload, and swap any number of local LLMs with full
client-side control, plus unified streaming across local and cloud backends.

Quickstart::

    from promptchain import ModelManager, Endpoint

    mgr = ModelManager(policy="auto", max_resident=1, idle_unload=300)
    mgr.register("drafter", Endpoint("lmstudio", "gemma-4-4b"))
    mgr.register("coder", Endpoint("ollama", "qwen3-coder:30b"))

    with mgr.use("coder") as m:          # evicts the drafter first if needed
        for token in m.stream(user_message="write a fizzbuzz in rust"):
            print(token, end="", flush=True)
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("promptchain")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0.dev0"

from .backends import (
    BACKEND_DEFAULTS,
    BACKEND_LABELS,
    CLOUD_BACKENDS,
    ENV_KEY_NAMES,
    MANAGED_BACKENDS,
    auth_headers,
    chat_completions_url,
    is_cloud,
    is_managed,
    models_url,
)
from .costs import (
    estimate_cost,
    format_stream_stats,
    parse_size,
    rough_token_count,
)
from .discovery import (
    get_models,
    test_connection,
    wait_until_ready,
)
from .endpoint import Endpoint
from .errors import (
    AuthenticationError,
    BackendConnectionError,
    BackendResponseError,
    GenerationTimeout,
    ModelNotRegistered,
    ModelNotResident,
    PromptChainError,
)
from .lifecycle import (
    load_model,
    loaded_models,
    unload_model,
)
from .manager import BoundModel, ModelManager
from .streaming import (
    StreamingResponse,
    ThinkTagFilter,
    ToolCallFilter,
    generate_completion,
    stream,
    stream_completion,
)

__all__ = [
    "__version__",
    # manager
    "ModelManager", "BoundModel", "Endpoint",
    # streaming
    "stream", "stream_completion", "generate_completion",
    "StreamingResponse", "ThinkTagFilter", "ToolCallFilter",
    # lifecycle
    "load_model", "unload_model", "loaded_models",
    # discovery
    "get_models", "test_connection", "wait_until_ready",
    # backends
    "BACKEND_DEFAULTS", "BACKEND_LABELS", "CLOUD_BACKENDS", "ENV_KEY_NAMES",
    "MANAGED_BACKENDS", "is_cloud", "is_managed",
    "chat_completions_url", "models_url", "auth_headers",
    # costs
    "estimate_cost", "rough_token_count", "format_stream_stats", "parse_size",
    # errors
    "PromptChainError", "BackendConnectionError", "GenerationTimeout",
    "BackendResponseError", "AuthenticationError",
    "ModelNotRegistered", "ModelNotResident",
]
