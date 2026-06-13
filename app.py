"""
PromptChain — Main Application Entry Point

Chains two LLMs together: a Prompter that refines your idea into
a detailed prompt, and a Coder that turns that prompt into working code.
"""

import time

import streamlit as st

from core.config import config_exists, load_config, get_role_endpoint
from core.api import test_connection, unload_model, is_cloud, estimate_cost, BACKEND_LABELS
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
from ui.landing import render_landing
from ui.chat import render_chat
from ui.presets import render_presets_manager

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
        # Top-level page: 'landing' | 'pipeline' | 'chat_prompter' | 'chat_coder'
        "page": "landing",
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
        # One-shot flags so retries/generation only run when explicitly
        # requested, never as a side effect of an unrelated rerun.
        "prompter_retry": False,
        "review_retry": False,
        "coder_pending": False,
        "coder_error": "",
        "coder_partial": "",
        # 'full' = prompt → code; 'refine' = multi-turn follow-up that sends
        # the previous code + an instruction so the coder edits in place
        "coder_mode": "full",
        "refine_instruction": "",
        # True after the prompter has run, so the coder step knows a
        # VRAM swap is actually needed (regenerating from the output
        # page skips the pointless unload).
        "needs_swap": False,
        # Which role's model most recently handled a request (pipeline or
        # chat), so all generation paths can swap VRAM cooperatively.
        "last_model_role": None,
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
    st.session_state["coder_mode"] = "full"
    st.session_state["refine_instruction"] = ""
    st.session_state["needs_swap"] = False
    st.session_state["show_settings"] = False
    # Drop widget state so inputs re-initialize cleanly
    for key in (
        "task_input_area",
        "prompt_review_area",
        "output_prompt_area",
        "output_filename",
        "output_folder_display",
        "refine_instruction_area",
    ):
        st.session_state.pop(key, None)


def load_history_entry(entry: dict):
    """Open a past run on the output page."""
    reset_pipeline()
    st.session_state["task_description"] = entry.get("task", "")
    st.session_state["generated_prompt"] = entry.get("prompt", "")
    st.session_state["generated_code"] = entry.get("code", "")
    st.session_state["current_step"] = STEP_CODE_OUTPUT
    st.session_state["page"] = "pipeline"

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
def _check_connection(base_url: str, backend: str, api_key: str) -> bool:
    """Cached connection check — refreshes every 30 seconds."""
    if is_cloud(backend) and not api_key:
        return False
    ok, _ = test_connection(base_url, backend, api_key)
    return ok

with st.sidebar:
    st.markdown("# PromptChain")

    if st.button("Home", key="nav_home_btn", use_container_width=True):
        st.session_state["page"] = "landing"
        st.rerun()

    if st.button("＋ New task", key="new_task_btn", use_container_width=True):
        reset_pipeline()
        st.session_state["page"] = "pipeline"
        st.rerun()

    if st.button("Prompter chat", key="nav_chat_prompter_btn", use_container_width=True):
        st.session_state["page"] = "chat_prompter"
        st.rerun()

    if st.button("Coder chat", key="nav_chat_coder_btn", use_container_width=True):
        st.session_state["page"] = "chat_coder"
        st.rerun()

    if st.button("Presets", key="nav_presets_btn", use_container_width=True):
        st.session_state["page"] = "presets"
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

    # Per-role endpoint: backend label, model, and a connection badge each
    st.markdown("**Endpoints**")
    for role, role_label in (("prompter", "Prompter"), ("coder", "Coder")):
        ep = get_role_endpoint(config, role)
        backend_label = BACKEND_LABELS.get(ep["backend"], ep["backend"])
        render_model_info(f"{role_label} · {backend_label}", ep["model"])
        connected = _check_connection(
            ep["base_url"], ep["backend"], ep["api_key"]
        ) if ep["base_url"] else False
        # Explain a red badge on hover: missing key vs. unreachable server
        if connected:
            reason = ""
        elif is_cloud(ep["backend"]) and not ep["api_key"]:
            reason = f"No API key set for {backend_label}"
        else:
            reason = f"Can't reach {ep['base_url'] or 'the server'}"
        render_connection_badge(connected, reason)

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

# ═══════════════════════════════════════════════════════
#  Main Content
# ═══════════════════════════════════════════════════════

if st.session_state.pop("_settings_saved_toast", False):
    st.toast("Settings saved")

if st.session_state.pop("_gen_stopped_toast", False):
    st.toast("Generation stopped")

# --- Settings Page ---
if st.session_state["show_settings"]:
    render_settings()
    st.stop()

# --- Landing Page (works even before models are configured) ---
if st.session_state["page"] == "landing":
    landing_action = render_landing(config)
    if landing_action:
        st.session_state["page"] = landing_action
        st.rerun()
    st.stop()

# --- Presets Manager (no models required) ---
if st.session_state["page"] == "presets":
    render_presets_manager(config)
    st.stop()

# --- Check if config is valid (pipeline and chats need models) ---
if not config.get("prompter_model") or not config.get("coder_model"):
    st.warning("Please configure your models in Settings before starting.")
    render_settings()
    st.stop()

# --- Chat Pages ---
if st.session_state["page"] == "chat_prompter":
    render_chat("prompter", config)
    st.stop()

if st.session_state["page"] == "chat_coder":
    render_chat("coder", config)
    st.stop()

# --- Step Indicator ---
render_step_indicator(st.session_state["current_step"])


# ═══════════════════════════════════════════════════════
#  Streaming Helper
# ═══════════════════════════════════════════════════════

def run_streaming_generation(
    role: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
    display_mode: str = "text",
    timeout: int = CODER_TIMEOUT,
    on_first_token=None,
    messages: list[dict] | None = None,
    partial_key: str | None = None,
):
    """
    Run a streaming generation and display output in real-time.

    Args:
        role: 'prompter' or 'coder' — its backend/base_url/model/api_key are
            resolved via get_role_endpoint(), so each role can use a different
            (local or cloud) backend.
        system_prompt: System prompt string.
        user_message: User message to send.
        temperature: Sampling temperature for this role.
        max_tokens: Max output tokens for this role.
        display_mode: 'text' for prompter (plain text), 'code' for coder (code block).
        timeout: Request timeout in seconds (180s for prompter, 900s for coder).
        on_first_token: Optional callback invoked when the first token arrives
            (the model is actually loaded at that point).
        messages: Optional full message list for multi-turn calls (refine mode);
            overrides system_prompt/user_message when provided.
        partial_key: Optional session-state key to write partial output to on
            every chunk, so a user-initiated Stop (which kills the script
            mid-loop) doesn't lose what was already generated.

    Returns:
        tuple: (full_output: str, error: str). error is empty on success.
    """
    endpoint = get_role_endpoint(config, role)
    full_output = ""
    first_token = True
    chunk_count = 0
    usage: dict = {}
    start_time = time.perf_counter()

    try:
        stream = stream_completion(
            base_url=endpoint["base_url"],
            model=endpoint["model"],
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            max_tokens=max_tokens,
            backend=endpoint["backend"],
            timeout=timeout,
            messages=messages,
            api_key=endpoint["api_key"],
            usage_out=usage,
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
            if partial_key:
                st.session_state[partial_key] = full_output
            if display_mode == "code":
                output_placeholder.code(full_output, line_numbers=True)
            else:
                output_placeholder.markdown(full_output)

        elapsed = time.perf_counter() - start_time
        stats = []
        if chunk_count and elapsed > 0:
            # One SSE chunk is roughly one token
            stats.append(
                f"~{chunk_count} tokens in {elapsed:.1f}s "
                f"({chunk_count / elapsed:.1f} tok/s)"
            )
        if usage.get("input_tokens") is not None or usage.get("output_tokens") is not None:
            # Exact billed counts (cloud backends report these)
            stats.append(
                f"{usage.get('input_tokens', '?')} in / "
                f"{usage.get('output_tokens', '?')} out tokens"
            )
            cost = estimate_cost(
                endpoint["model"],
                usage.get("input_tokens"),
                usage.get("output_tokens"),
            )
            if cost is not None:
                stats.append(f"~${cost:.4f} est.")
        if stats:
            st.caption(" · ".join(stats))

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


def _role_is_local(role: str) -> bool:
    """True when the role's backend is a local server (occupies VRAM)."""
    return not is_cloud(get_role_endpoint(config, role)["backend"])


def _stop_prompter():
    """on_click for the Stop button shown while the prompter streams.
    The click itself interrupts the running script at its next placeholder
    update; this callback just records the consequences."""
    st.session_state["_gen_stopped_toast"] = True
    # A local prompter is now resident in VRAM and must be swapped out before
    # the coder runs; a cloud prompter occupies nothing.
    st.session_state["needs_swap"] = _role_is_local("prompter")


def run_prompter(status_placeholder) -> tuple[str, str]:
    """Stream the prompter model. Returns (result, error)."""

    # A local coder model left loaded by a chat or earlier run would fight the
    # prompter for VRAM — evict it first. (No-op for a cloud coder.)
    if st.session_state.get("last_model_role") == "coder":
        coder = get_role_endpoint(config, "coder")
        unload_model(coder["base_url"], coder["model"], coder["backend"])
    st.session_state["last_model_role"] = "prompter"

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
        role="prompter",
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
        st.button("Stop", key="stop_prompter_btn", on_click=_stop_prompter)

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
            # A local prompter now occupies VRAM and must be swapped out
            # before the coder runs; a cloud prompter occupies nothing.
            st.session_state["needs_swap"] = _role_is_local("prompter")
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
        st.button("Stop", key="stop_prompter_retry_btn", on_click=_stop_prompter)

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
            st.session_state["needs_swap"] = _role_is_local("prompter")
            # Drop stale widget state so the text area picks up the new prompt
            st.session_state.pop("prompt_review_area", None)
            st.rerun()

    elif action == "confirm":
        st.session_state["current_step"] = STEP_GENERATING
        st.session_state["coder_pending"] = True
        st.session_state["coder_mode"] = "full"
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
        st.session_state["coder_mode"] = "full"
        st.session_state["current_step"] = STEP_PROMPT_REVIEW

    def _stop_coder():
        # The click interrupts the streaming loop; the progressive
        # coder_partial writes preserve what was generated so far, and the
        # rerun lands in the stable error view below.
        st.session_state["coder_error"] = "Stopped by user."
        st.session_state["_gen_stopped_toast"] = True

    # Generation only runs when explicitly requested via the one-shot flag.
    # Reruns triggered by button clicks land in the branches below instead
    # of re-executing the whole unload + generation pipeline.
    if st.session_state.pop("coder_pending", False):
        st.session_state["is_running"] = True
        status_placeholder = st.empty()

        # Only swap if a local prompter actually ran since the last unload —
        # regenerating from the output page (or a cloud prompter) would
        # otherwise trigger a pointless unload.
        if st.session_state.pop("needs_swap", False):
            with status_placeholder.container():
                render_pipeline_checklist([
                    {"label": "Prompt confirmed", "state": "done"},
                    {"label": "Unloading Prompter model...", "state": "running"},
                    {"label": "Loading Coder model", "state": "pending"},
                    {"label": "Generating code", "state": "pending"},
                ])

            prompter = get_role_endpoint(config, "prompter")
            unload_model(prompter["base_url"], prompter["model"], prompter["backend"])

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

        st.button("Stop", key="stop_coder_btn", on_click=_stop_coder)
        st.markdown("### Coder output")

        # Refine mode: multi-turn call with the previous prompt + code +
        # the follow-up instruction, so the coder edits in place instead
        # of regenerating from scratch.
        refine_mode = (
            st.session_state.get("coder_mode") == "refine"
            and st.session_state.get("generated_code")
        )
        if refine_mode:
            coder_messages = [
                {"role": "system", "content": st.session_state["coder_system"]},
                {"role": "user", "content": st.session_state["generated_prompt"]},
                {"role": "assistant", "content": st.session_state["generated_code"]},
                {
                    "role": "user",
                    "content": (
                        "Update the code above according to the following "
                        "instructions. Output the complete updated code in a "
                        "single fenced code block — no diffs, no omitted "
                        "sections.\n\n"
                        + st.session_state.get("refine_instruction", "")
                    ),
                },
            ]
        else:
            coder_messages = None

        st.session_state["last_model_role"] = "coder"

        result, error = run_streaming_generation(
            role="coder",
            system_prompt=st.session_state["coder_system"],
            user_message=st.session_state["generated_prompt"],
            temperature=config["coder_temperature"],
            max_tokens=config["coder_max_tokens"],
            display_mode="code",
            timeout=CODER_TIMEOUT,
            on_first_token=_on_first_token,
            messages=coder_messages,
            partial_key="coder_partial",
        )
        st.session_state["is_running"] = False

        if error:
            st.session_state["coder_error"] = error
            st.session_state["coder_partial"] = result
            st.rerun()  # re-render into the stable error view below
        else:
            st.session_state["generated_code"] = result
            st.session_state["coder_partial"] = ""
            st.session_state["coder_mode"] = "full"
            st.session_state["refine_instruction"] = ""
            st.session_state.pop("refine_instruction_area", None)
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
        st.session_state["coder_mode"] = "full"
        st.session_state["coder_error"] = ""
        st.session_state["coder_partial"] = ""
        st.rerun()

    elif action == "refine":
        # Multi-turn follow-up: previous code + instruction → updated code
        st.session_state["current_step"] = STEP_GENERATING
        st.session_state["coder_pending"] = True
        st.session_state["coder_mode"] = "refine"
        st.session_state["coder_error"] = ""
        st.session_state["coder_partial"] = ""
        st.rerun()

    elif action == "start_over":
        # Unload a local coder model to free VRAM, then reset for a fresh task
        coder = get_role_endpoint(config, "coder")
        unload_model(coder["base_url"], coder["model"], coder["backend"])
        st.session_state["last_model_role"] = None
        reset_pipeline()
        st.rerun()
