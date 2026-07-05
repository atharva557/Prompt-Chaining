"""
PromptChain — Direct Chat Pages

ChatGPT-style chat with a single model: one page for the Prompter, one for
the Coder. Chats share VRAM cooperatively with the pipeline via the
st.session_state["last_model_role"] key — before generating, the *other*
role's model is unloaded if it was the last one to run.
"""

import time

import streamlit as st

from core.api import unload_model, is_cloud, format_stream_stats, BACKEND_LABELS, cancel_unload
from core.chats import load_chat_messages, save_chat_messages
from core.config import get_role_endpoint, swap_enabled
from core.streaming import stream_completion, PROMPTER_TIMEOUT, CODER_TIMEOUT
from ui.code_output import extract_code

# app.py's STEP_PROMPT_REVIEW — the pipeline step a chat prompt is handed to
_STEP_PROMPT_REVIEW = 1

# Starter prompts shown on an empty chat
ROLE_EXAMPLES = {
    "prompter": [
        "A React calculator with keyboard support",
        "A Python script that watches a folder for new files",
        "A CLI that converts CSV to JSON",
    ],
    "coder": [
        "Write a debounce function in TypeScript",
        "Explain async/await with a short example",
        "A regex to validate an email, with tests",
    ],
}

# Chat-specific defaults: the pipeline system prompts demand rigid output
# ("output ONLY the prompt" / "a single fenced block, no prose"), which is
# wrong for a conversation. These stay conversational.
CHAT_PROMPTER_SYSTEM = """You are an expert prompt engineer for coding LLMs. Help the user draft, critique, and iteratively refine prompts. When asked to produce a prompt, output it as a clearly delimited markdown block; otherwise answer conversationally and concisely."""

CHAT_CODER_SYSTEM = """You are an expert software engineer. Answer coding questions, write and debug code, and explain trade-offs concisely. Use fenced code blocks with language tags for all code."""

ROLE_META = {
    "prompter": {
        "label": "Prompter",
        "other": "coder",
        "temp_key": "prompter_temperature",
        "tokens_key": "prompter_max_tokens",
        "timeout": PROMPTER_TIMEOUT,
        "default_system": CHAT_PROMPTER_SYSTEM,
        "placeholder": "Describe a coding task to turn into a structured prompt…",
    },
    "coder": {
        "label": "Coder",
        "other": "prompter",
        "temp_key": "coder_temperature",
        "tokens_key": "coder_max_tokens",
        "timeout": CODER_TIMEOUT,
        "default_system": CHAT_CODER_SYSTEM,
        "placeholder": "Ask a coding question or describe what to build…",
    },
}


def _handoff_to_pipeline(msgs: list[dict], idx: int) -> None:
    """Open the pipeline's review step with the assistant message at `idx`
    as the generated prompt (the fenced block if there is one, since the
    chat Prompter wraps prompts in conversational text)."""
    prompt_text, _lang = extract_code(msgs[idx]["content"])
    # The nearest preceding user message doubles as the task description
    task = next(
        (m["content"] for m in reversed(msgs[:idx]) if m["role"] == "user"), ""
    )
    if task:
        st.session_state["task_description"] = task
    st.session_state["generated_prompt"] = prompt_text
    st.session_state["current_step"] = _STEP_PROMPT_REVIEW
    st.session_state["coder_mode"] = "full"
    st.session_state["coder_error"] = ""
    st.session_state["coder_partial"] = ""
    st.session_state["page"] = "pipeline"
    # Drop stale widget state so the review/task areas show the new content
    st.session_state.pop("prompt_review_area", None)
    st.session_state.pop("task_input_area", None)


def render_chat(role: str, config: dict) -> None:
    """Render a full chat page for 'prompter' or 'coder'."""
    meta = ROLE_META[role]
    msgs_key = f"chat_{role}_messages"
    partial_key = f"chat_{role}_partial"
    system_key = f"chat_{role}_system"

    if msgs_key not in st.session_state:
        # Conversations persist across restarts (chats.json)
        st.session_state[msgs_key] = load_chat_messages(role)
    if system_key not in st.session_state:
        st.session_state[system_key] = meta["default_system"]

    msgs = st.session_state[msgs_key]

    # Salvage output from a stopped stream: the Stop button (any click,
    # really) kills the script mid-loop, so the reply never got appended.
    # The per-chunk session-state writes below preserve what had streamed.
    partial = st.session_state.pop(partial_key, "")
    if partial and msgs and msgs[-1]["role"] == "user":
        msgs.append(
            {"role": "assistant", "content": partial + "\n\n*— stopped —*"}
        )
        save_chat_messages(role, msgs)

    def _clear_chat():
        st.session_state[msgs_key].clear()
        save_chat_messages(role, [])

    endpoint = get_role_endpoint(config, role)
    model = endpoint["model"]

    col_title, col_clear = st.columns([4, 1])
    with col_title:
        st.markdown(f"## {meta['label']} chat")
        st.caption(
            f"Chatting directly with `{model}` on "
            f"{BACKEND_LABELS.get(endpoint['backend'], endpoint['backend'])} · "
            f"temperature {config.get(meta['temp_key'], 0.3)}"
        )
    with col_clear:
        st.button(
            "Clear chat",
            key=f"chat_{role}_clear",
            use_container_width=True,
            on_click=_clear_chat,
        )

    with st.expander("System prompt", expanded=False):
        st.session_state[system_key] = st.text_area(
            "System prompt",
            value=st.session_state[system_key],
            height=140,
            key=f"chat_{role}_system_area",
            label_visibility="collapsed",
        )

    # ── Conversation history ──
    for i, m in enumerate(msgs):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            # Prompter replies can jump straight into the pipeline: the
            # message becomes the prompt awaiting review before the Coder runs
            if role == "prompter" and m["role"] == "assistant" and m["content"].strip():
                if st.button(
                    "Use as pipeline prompt",
                    key=f"chat_use_in_pipeline_{i}",
                    help=(
                        "Open the pipeline's review step with this message "
                        "as the prompt for the Coder"
                    ),
                ):
                    _handoff_to_pipeline(msgs, i)
                    st.rerun()

    # chat_input always pins to the page bottom; a clicked example seeds it
    seeded = st.session_state.pop(f"chat_{role}_seed", "")
    typed = st.chat_input(meta["placeholder"], key=f"chat_{role}_input")
    user_msg = typed or seeded

    if not user_msg:
        # Empty-state: offer a few starter prompts
        if not msgs:
            st.caption("Not sure where to start? Try one of these:")
            ex_cols = st.columns(len(ROLE_EXAMPLES[role]))
            for i, example in enumerate(ROLE_EXAMPLES[role]):
                if ex_cols[i].button(
                    example, key=f"chat_{role}_ex_{i}", use_container_width=True
                ):
                    st.session_state[f"chat_{role}_seed"] = example
                    st.rerun()
        return

    msgs.append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    # ── Cooperative VRAM swap (pipeline + other chat) ──
    # Evict the other role's local model; no-op when it's a cloud backend
    # or when the swap policy says both models fit in VRAM.
    other = meta["other"]
    other_ep = get_role_endpoint(config, other)
    if (
        st.session_state.get("last_model_role") == other
        and not is_cloud(other_ep["backend"])
        and swap_enabled(config)
    ):
        with st.spinner(f"Unloading {ROLE_META[other]['label']} model…"):
            unload_model(other_ep["base_url"], other_ep["model"], other_ep["backend"])
    st.session_state["last_model_role"] = role
    # A reply is about to stream — cancel any pending idle-unload of this model.
    cancel_unload()
    # Tell the pipeline whether a *local* prompter currently occupies VRAM
    st.session_state["needs_swap"] = (role == "prompter") and not is_cloud(endpoint["backend"])

    # Clicking any button interrupts the stream at its next placeholder
    # update; the partial is salvaged on the rerun (top of this function)
    stop_slot = st.empty()
    stop_slot.button("Stop", key=f"chat_{role}_stop")

    with st.chat_message("assistant"):
        reasoning_slot = st.empty()
        reasoning_box = None
        out = st.empty()
        stats_slot = st.empty()
        full = ""
        error = ""
        chunk_count = 0
        usage: dict = {}
        reasoning: dict = {}
        start = time.perf_counter()

        try:
            api_messages = (
                [{"role": "system", "content": st.session_state[system_key]}]
                + msgs
            )
            stream = stream_completion(
                base_url=endpoint["base_url"],
                model=model,
                messages=api_messages,
                temperature=config.get(meta["temp_key"], 0.3),
                max_tokens=config.get(meta["tokens_key"], 2048),
                backend=endpoint["backend"],
                timeout=meta["timeout"],
                api_key=endpoint["api_key"],
                usage_out=usage,
                reasoning_out=reasoning,
            )
            for token in stream:
                # Thinking models: hidden reasoning goes into a collapsed
                # expander above the reply, not into the reply itself
                if reasoning.get("text"):
                    if reasoning_box is None:
                        with reasoning_slot.container():
                            with st.expander("Model reasoning", expanded=False):
                                reasoning_box = st.empty()
                    reasoning_box.markdown(reasoning["text"])
                if not token:
                    continue  # reasoning-only chunk
                chunk_count += 1
                full += token
                st.session_state[partial_key] = full
                out.markdown(full + " ▌")
                if chunk_count % 24 == 0:
                    elapsed = time.perf_counter() - start
                    if elapsed > 0:
                        stats_slot.caption(
                            f"~{chunk_count} tokens · {chunk_count / elapsed:.1f} tok/s"
                        )
        except (ConnectionError, TimeoutError, RuntimeError) as e:
            error = str(e)
        except Exception as e:
            error = f"Unexpected error: {e}"

        if error:
            full = (
                full + f"\n\n*— interrupted: {error} —*"
                if full
                else f"*{error}*"
            )
        out.markdown(full)

        if chunk_count and not error:
            stats_line = format_stream_stats(
                model, chunk_count, time.perf_counter() - start, usage
            )
            if stats_line:
                stats_slot.caption(stats_line)

    msgs.append({"role": "assistant", "content": full})
    save_chat_messages(role, msgs)
    st.session_state.pop(partial_key, None)
    stop_slot.empty()
