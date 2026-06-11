"""
PromptChain — Main Application Entry Point

Chains two LLMs together: a Prompter that refines your idea into
a detailed prompt, and a Coder that turns that prompt into working code.
"""

import time

import streamlit as st

from core.config import config_exists, load_config
from core.api import test_connection, unload_model
from core.history import load_history, add_entry, delete_entry, clear_history
from core.streaming import stream_completion, PROMPTER_TIMEOUT, CODER_TIMEOUT
from ui.styles import (
    inject_custom_css,
    render_step_indicator,
    render_connection_badge,
    render_model_info,
    render_divider,
)
from ui.settings import render_settings
from ui.task_input import render_task_input, DEFAULT_PROMPTER_SYSTEM, DEFAULT_CODER_SYSTEM
from ui.prompt_review import render_prompt_review
from ui.code_output import render_code_output

# ═══════════════════════════════════════════════════════
#  Page Config
# ═══════════════════════════════════════════════════════

st.set_page_config(
    page_title="PromptChain",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════
#  Custom CSS
# ═══════════════════════════════════════════════════════

inject_custom_css()

# ═══════════════════════════════════════════════════════
#  Session State Initialization
# ═══════════════════════════════════════════════════════

# Step constants
STEP_TASK_INPUT = 0
STEP_PROMPT_REVIEW = 1
STEP_GENERATING = 2
STEP_CODE_OUTPUT = 3

def init_session_state():
    """Initialize all session state keys with defaults."""
    defaults = {
        "current_step": STEP_TASK_INPUT,
        "task_description": "",
        "generated_prompt": "",
        "generated_code": "",
        "detected_language": "python",
        "prompter_system": DEFAULT_PROMPTER_SYSTEM,
        "coder_system": DEFAULT_CODER_SYSTEM,
        "config": None,
        "is_running": False,
        "show_settings": False,
        "available_models": [],
        # One-shot flags so retries/generation only run when explicitly
        # requested, never as a side effect of an unrelated rerun.
        "prompter_retry": False,
        "review_retry": False,
        "coder_pending": False,
        "coder_error": "",
        "coder_partial": "",
        # True after the prompter has run, so the coder step knows a
        # VRAM swap is actually needed (regenerating from the output
        # page skips the pointless unload).
        "needs_swap": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()


def reset_pipeline():
    """Reset pipeline state for a fresh task (keeps settings and system prompts)."""
    st.session_state["current_step"] = STEP_TASK_INPUT
    st.session_state["task_description"] = ""
    st.session_state["generated_prompt"] = ""
    st.session_state["generated_code"] = ""
    st.session_state["is_running"] = False
    st.session_state["coder_pending"] = False
    st.session_state["coder_error"] = ""
    st.session_state["coder_partial"] = ""
    st.session_state["needs_swap"] = False
    st.session_state["show_settings"] = False
    # Drop widget state so inputs re-initialize cleanly
    for key in (
        "task_input_area",
        "prompt_review_area",
        "output_prompt_area",
        "output_filename",
        "output_folder_display",
    ):
        st.session_state.pop(key, None)


def load_history_entry(entry: dict):
    """Open a past run on the output page."""
    reset_pipeline()
    st.session_state["task_description"] = entry.get("task", "")
    st.session_state["generated_prompt"] = entry.get("prompt", "")
    st.session_state["generated_code"] = entry.get("code", "")
    st.session_state["current_step"] = STEP_CODE_OUTPUT

# ═══════════════════════════════════════════════════════
#  Load Config
# ═══════════════════════════════════════════════════════

if st.session_state["config"] is None:
    st.session_state["config"] = load_config()

config = st.session_state["config"]

# First run (no valid config): open Settings once, but don't force the
# user back into it on every rerun — that was a navigation trap.
if not config_exists() and not st.session_state.get("_first_run_handled"):
    st.session_state["show_settings"] = True
    st.session_state["_settings_just_opened"] = True
    st.session_state["_first_run_handled"] = True

# ═══════════════════════════════════════════════════════
#  Sidebar
# ═══════════════════════════════════════════════════════

# Cache sidebar connection check to avoid latency on every rerun
@st.cache_data(ttl=30, show_spinner=False)
def _check_connection(base_url: str, backend: str) -> bool:
    """Cached connection check — refreshes every 30 seconds."""
    ok, _ = test_connection(base_url, backend)
    return ok

with st.sidebar:
    st.markdown("# PromptChain")

    if st.button("＋ New task", key="new_task_btn", use_container_width=True):
        reset_pipeline()
        st.rerun()

    render_divider()

    # ── History ──
    st.markdown("**History**")
    history = load_history()
    if not history:
        st.caption("No previous runs yet.")
    else:
        for entry in history[:10]:
            task_text = entry.get("task", "") or "(untitled)"
            label = task_text[:32] + ("…" if len(task_text) > 32 else "")
            date = entry.get("timestamp", "")[:16].replace("T", " ")
            col_open, col_del = st.columns([5, 1])
            with col_open:
                if st.button(
                    label,
                    key=f"hist_{entry['id']}",
                    use_container_width=True,
                    help=f"{date} — {task_text}",
                ):
                    load_history_entry(entry)
                    st.rerun()
            with col_del:
                if st.button(
                    "✕",
                    key=f"histdel_{entry['id']}",
                    help="Delete this run",
                ):
                    delete_entry(entry["id"])
                    st.rerun()
        if len(history) > 10:
            st.caption(f"+ {len(history) - 10} older run(s)")
        if st.button("Clear history", key="clear_history_btn", use_container_width=True):
            clear_history()
            st.rerun()

    render_divider()

    # Connection status (cached to avoid sidebar lag)
    st.markdown("**Server**")
    if config.get("base_url"):
        connected = _check_connection(
            config["base_url"],
            config.get("backend", "lmstudio")
        )
        render_connection_badge(connected)
    else:
        render_connection_badge(False)

    render_divider()

    # Model info
    render_model_info("Prompter", config.get("prompter_model", ""))
    render_model_info("Coder", config.get("coder_model", ""))

    render_divider()

    # Settings toggle button
    if st.button(
        "Settings",
        key="sidebar_settings_btn",
        use_container_width=True,
    ):
        st.session_state["show_settings"] = not st.session_state["show_settings"]
        # Flag so settings page re-syncs widget keys with current config
        if st.session_state["show_settings"]:
            st.session_state["_settings_just_opened"] = True
        st.rerun()

    # Backend indicator
    backend = config.get("backend", "lmstudio")
    backend_label = "LM Studio" if backend == "lmstudio" else "Ollama"
    st.caption(f"Backend: {backend_label}")

# ═══════════════════════════════════════════════════════
#  Main Content
# ═══════════════════════════════════════════════════════

if st.session_state.pop("_settings_saved_toast", False):
    st.toast("Settings saved")

# --- Settings Page ---
if st.session_state["show_settings"]:
    render_settings()
    st.stop()

# --- Check if config is valid ---
if not config.get("prompter_model") or not config.get("coder_model"):
    st.warning("Please configure your models in Settings before starting.")
    render_settings()
    st.stop()

# --- Step Indicator ---
render_step_indicator(st.session_state["current_step"])


# ═══════════════════════════════════════════════════════
#  Streaming Helper
# ═══════════════════════════════════════════════════════

def run_streaming_generation(
    model_key: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
    display_mode: str = "text",
    timeout: int = CODER_TIMEOUT,
    on_first_token=None,
):
    """
    Run a streaming generation and display output in real-time.

    Args:
        model_key: Config key for the model name ('prompter_model' or 'coder_model').
        system_prompt: System prompt string.
        user_message: User message to send.
        temperature: Sampling temperature for this role.
        max_tokens: Max output tokens for this role.
        display_mode: 'text' for prompter (plain text), 'code' for coder (code block).
        timeout: Request timeout in seconds (180s for prompter, 900s for coder).
        on_first_token: Optional callback invoked when the first token arrives
            (the model is actually loaded at that point).

    Returns:
        tuple: (full_output: str, error: str). error is empty on success.
    """
    full_output = ""
    first_token = True
    chunk_count = 0
    start_time = time.perf_counter()

    try:
        stream = stream_completion(
            base_url=config["base_url"],
            model=config[model_key],
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            max_tokens=max_tokens,
            backend=config.get("backend", "lmstudio"),
            timeout=timeout,
        )

        # Create a placeholder for streaming output
        output_placeholder = st.empty()

        for token in stream:
            if first_token:
                first_token = False
                if on_first_token:
                    on_first_token()
            chunk_count += 1
            full_output += token
            if display_mode == "code":
                output_placeholder.code(full_output, line_numbers=True)
            else:
                output_placeholder.markdown(full_output)

        elapsed = time.perf_counter() - start_time
        if chunk_count and elapsed > 0:
            # One SSE chunk is roughly one token
            st.caption(
                f"~{chunk_count} tokens in {elapsed:.1f}s "
                f"({chunk_count / elapsed:.1f} tok/s)"
            )

        return full_output, ""

    except ConnectionError as e:
        return full_output, str(e)
    except TimeoutError as e:
        return full_output, str(e)
    except RuntimeError as e:
        return full_output, str(e)
    except Exception as e:
        return full_output, f"Unexpected error: {str(e)}"


# ═══════════════════════════════════════════════════════
#  Pipeline Status Checklist
# ═══════════════════════════════════════════════════════

def render_pipeline_checklist(stages: list[dict]):
    """
    Render a live pipeline status checklist.

    Each stage dict has:
        - label: str
        - state: 'done' | 'running' | 'pending' | 'error'
    """
    icons = {
        "done": "✓",
        "running": '<span class="spinner"></span>',
        "pending": "○",
        "error": "✕",
    }
    colors = {
        "done": "var(--pc-success)",
        "running": "var(--pc-text)",
        "pending": "var(--pc-text-muted)",
        "error": "var(--pc-error)",
    }

    html = '<div style="margin: 1rem 0;">'
    for stage in stages:
        state = stage["state"]
        icon = icons.get(state, "○")
        color = colors.get(state, "var(--pc-text-muted)")
        font_weight = "600" if state == "running" else "400"
        html += (
            f'<div style="display:flex; align-items:center; gap:0.6rem; '
            f'padding:0.4rem 0; color:{color}; font-weight:{font_weight}; '
            f'font-family:Inter,sans-serif; font-size:0.9rem;">'
            f'{icon} {stage["label"]}</div>'
        )
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def run_prompter(status_placeholder) -> tuple[str, str]:
    """Stream the prompter model. Returns (result, error)."""

    def show_status(loaded: bool):
        with status_placeholder.container():
            render_pipeline_checklist([
                {
                    "label": "Prompter model loaded" if loaded else "Loading Prompter model...",
                    "state": "done" if loaded else "running",
                },
                {
                    "label": "Generating prompt..." if loaded else "Generating prompt",
                    "state": "running" if loaded else "pending",
                },
            ])

    show_status(loaded=False)
    st.markdown("### Prompter output")

    return run_streaming_generation(
        model_key="prompter_model",
        system_prompt=st.session_state["prompter_system"],
        user_message=st.session_state["task_description"],
        temperature=config["prompter_temperature"],
        max_tokens=config["prompter_max_tokens"],
        display_mode="text",
        timeout=PROMPTER_TIMEOUT,
        on_first_token=lambda: show_status(loaded=True),
    )


# ═══════════════════════════════════════════════════════
#  Step 0: Task Input
# ═══════════════════════════════════════════════════════

if st.session_state["current_step"] == STEP_TASK_INPUT:
    should_generate = render_task_input()
    retry_requested = st.session_state.pop("prompter_retry", False)

    if should_generate or retry_requested:
        st.session_state["is_running"] = True
        status_placeholder = st.empty()

        result, error = run_prompter(status_placeholder)
        st.session_state["is_running"] = False

        if error:
            with status_placeholder.container():
                render_pipeline_checklist([
                    {"label": "Prompter model loaded", "state": "done"},
                    {"label": f"Generation failed: {error}", "state": "error"},
                ])
            # on_click sets the flag BEFORE the rerun, so the next run
            # actually re-executes the generation (a bare rerun would not).
            st.button(
                "Retry",
                key="retry_prompter_error",
                on_click=lambda: st.session_state.update(prompter_retry=True),
            )
        else:
            st.session_state["generated_prompt"] = result
            st.session_state["needs_swap"] = True  # prompter is now loaded
            st.session_state["current_step"] = STEP_PROMPT_REVIEW
            # Drop stale widget state so the review text area shows the new prompt
            st.session_state.pop("prompt_review_area", None)
            st.rerun()

# ═══════════════════════════════════════════════════════
#  Step 1: Prompt Review
# ═══════════════════════════════════════════════════════

elif st.session_state["current_step"] == STEP_PROMPT_REVIEW:
    action = render_prompt_review()
    if st.session_state.pop("review_retry", False):
        action = "retry"

    if action == "retry":
        st.session_state["is_running"] = True
        status_placeholder = st.empty()

        result, error = run_prompter(status_placeholder)
        st.session_state["is_running"] = False

        if error:
            with status_placeholder.container():
                render_pipeline_checklist([
                    {"label": f"Regeneration failed: {error}", "state": "error"},
                ])
            st.button(
                "Retry again",
                key="retry_prompt_again",
                on_click=lambda: st.session_state.update(review_retry=True),
            )
        else:
            st.session_state["generated_prompt"] = result
            st.session_state["needs_swap"] = True  # prompter is now loaded
            # Drop stale widget state so the text area picks up the new prompt
            st.session_state.pop("prompt_review_area", None)
            st.rerun()

    elif action == "confirm":
        st.session_state["current_step"] = STEP_GENERATING
        st.session_state["coder_pending"] = True
        st.session_state["coder_error"] = ""
        st.session_state["coder_partial"] = ""
        st.rerun()

# ═══════════════════════════════════════════════════════
#  Step 2: Model Swap + Coder Generation (Streaming)
# ═══════════════════════════════════════════════════════

elif st.session_state["current_step"] == STEP_GENERATING:

    def _retry_coder():
        st.session_state["coder_pending"] = True
        st.session_state["coder_error"] = ""
        st.session_state["coder_partial"] = ""

    def _back_to_prompt():
        st.session_state["coder_error"] = ""
        st.session_state["coder_partial"] = ""
        st.session_state["current_step"] = STEP_PROMPT_REVIEW

    # Generation only runs when explicitly requested via the one-shot flag.
    # Reruns triggered by button clicks land in the branches below instead
    # of re-executing the whole unload + generation pipeline.
    if st.session_state.pop("coder_pending", False):
        st.session_state["is_running"] = True
        status_placeholder = st.empty()

        # Only swap if the prompter actually ran since the last unload —
        # regenerating from the output page would otherwise reload the
        # prompter just to unload it (slow on Ollama).
        if st.session_state.pop("needs_swap", False):
            with status_placeholder.container():
                render_pipeline_checklist([
                    {"label": "Prompt confirmed", "state": "done"},
                    {"label": "Unloading Prompter model...", "state": "running"},
                    {"label": "Loading Coder model", "state": "pending"},
                    {"label": "Generating code", "state": "pending"},
                ])

            unload_model(
                config["base_url"],
                config["prompter_model"],
                config.get("backend", "lmstudio"),
            )

        # The coder actually loads during the first request — the checklist
        # flips to "loaded" when the first token arrives.
        with status_placeholder.container():
            render_pipeline_checklist([
                {"label": "Prompt confirmed", "state": "done"},
                {"label": "Prompter unloaded", "state": "done"},
                {"label": "Loading Coder model...", "state": "running"},
                {"label": "Generating code", "state": "pending"},
            ])

        def _on_first_token():
            with status_placeholder.container():
                render_pipeline_checklist([
                    {"label": "Prompt confirmed", "state": "done"},
                    {"label": "Prompter unloaded", "state": "done"},
                    {"label": "Coder model loaded", "state": "done"},
                    {"label": "Generating code...", "state": "running"},
                ])

        st.markdown("### Coder output")

        result, error = run_streaming_generation(
            model_key="coder_model",
            system_prompt=st.session_state["coder_system"],
            user_message=st.session_state["generated_prompt"],
            temperature=config["coder_temperature"],
            max_tokens=config["coder_max_tokens"],
            display_mode="code",
            timeout=CODER_TIMEOUT,
            on_first_token=_on_first_token,
        )
        st.session_state["is_running"] = False

        if error:
            st.session_state["coder_error"] = error
            st.session_state["coder_partial"] = result
            st.rerun()  # re-render into the stable error view below
        else:
            st.session_state["generated_code"] = result
            add_entry(
                task=st.session_state["task_description"],
                prompt=st.session_state["generated_prompt"],
                code=result,
                prompter_model=config.get("prompter_model", ""),
                coder_model=config.get("coder_model", ""),
            )
            st.session_state["current_step"] = STEP_CODE_OUTPUT
            # Drop stale widget state so the output page shows this run
            st.session_state.pop("output_prompt_area", None)
            st.rerun()

    elif st.session_state.get("coder_error"):
        render_pipeline_checklist([
            {"label": "Prompt confirmed", "state": "done"},
            {"label": "Prompter unloaded", "state": "done"},
            {"label": f"Generation failed: {st.session_state['coder_error']}", "state": "error"},
        ])

        if st.session_state.get("coder_partial"):
            st.warning("Partial output was generated before the error:")
            st.code(st.session_state["coder_partial"], line_numbers=True)

        col1, col2 = st.columns(2)
        with col1:
            st.button("Retry", key="retry_coder_btn", on_click=_retry_coder)
        with col2:
            st.button("Back to prompt", key="back_to_prompt_btn", on_click=_back_to_prompt)

    else:
        # Unreachable in the normal flow — recover gracefully
        st.info("Nothing in progress.")
        st.button("Back to prompt", key="back_to_prompt_fallback", on_click=_back_to_prompt)

# ═══════════════════════════════════════════════════════
#  Step 3: Code Output
# ═══════════════════════════════════════════════════════

elif st.session_state["current_step"] == STEP_CODE_OUTPUT:
    action = render_code_output()

    if action == "regenerate":
        # Re-run the coder with the (possibly edited) prompt
        st.session_state["current_step"] = STEP_GENERATING
        st.session_state["coder_pending"] = True
        st.session_state["coder_error"] = ""
        st.session_state["coder_partial"] = ""
        st.rerun()

    elif action == "start_over":
        # Unload coder model to free VRAM, then reset for a fresh task
        unload_model(
            config["base_url"],
            config["coder_model"],
            config.get("backend", "lmstudio"),
        )
        reset_pipeline()
        st.rerun()
