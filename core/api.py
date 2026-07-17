"""Compatibility shim — the implementation moved into the `promptchain`
package (src/promptchain/). This module re-exports the old core.api surface
so the Streamlit app keeps importing `core.api` until it migrates.

New code should import from `promptchain` directly.
"""

import requests   # noqa: F401  (kept so tests can patch core.api.requests.*)
import threading  # noqa: F401  (kept so tests can patch core.api.threading.*)

from promptchain.backends import (  # noqa: F401
    BACKEND_DEFAULTS,
    BACKEND_LABELS,
    CLOUD_BACKENDS,
    DEFAULT_TIMEOUT,
    ENV_KEY_NAMES,
    GENERATION_TIMEOUT,
    _auth_headers,
    auth_headers,
    chat_completions_url,
    is_cloud,
    models_url,
)
from promptchain.costs import (  # noqa: F401
    _PRICING,
    estimate_cost,
    format_stream_stats,
    rough_token_count,
)
from promptchain.discovery import (  # noqa: F401
    _anthropic_models,
    get_models,
    test_connection,
)
from promptchain.lifecycle import (  # noqa: F401
    _fire_unload,
    cancel_unload,
    consume_unload_fired,
    load_model,
    loaded_models,
    schedule_unload,
    unload_model,
)
from promptchain.streaming import generate_completion  # noqa: F401
