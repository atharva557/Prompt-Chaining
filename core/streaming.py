"""Compatibility shim — the implementation moved into the `promptchain`
package (src/promptchain/streaming.py). This module re-exports the old
core.streaming surface so the Streamlit app keeps importing `core.streaming`
until it migrates.

The role-named timeouts are an app concept (the library has a single
DEFAULT_STREAM_TIMEOUT), so they live here now.
"""

from promptchain.streaming import (  # noqa: F401
    DEFAULT_STREAM_TIMEOUT,
    StreamingResponse,
    ThinkTagFilter,
    ToolCallFilter,
    _anthropic_omits_temperature,
    _is_sampling_param_error,
    _partial_suffix_len,
    stream,
    stream_completion,
)

# Default timeouts per role
PROMPTER_TIMEOUT = 180   # 3 minutes for small/fast prompter models
CODER_TIMEOUT = 900      # 15 minutes for larger coder models
