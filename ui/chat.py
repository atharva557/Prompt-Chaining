"""
PromptChain — Direct Chat Pages

ChatGPT-style chat with a single model: one page for the Prompter, one for
the Coder. Chats share VRAM cooperatively with the pipeline via the
st.session_state["last_model_role"] key — before generating, the *other*
role's model is unloaded if it was the last one to run.
"""

import time

import streamlit as st

from core.api import unload_model, is_cloud, estimate_cost, BACKEND_LABELS, cancel_unload
from core.config import get_role_endpoint
from core.streaming import stream_completion, PROMPTER_TIMEOUT, CODER_TIMEOUT

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


def render_chat(role: str, config: dict) -> None:
    """Render a full chat page for 'prompter' or 'coder'."""
    meta = ROLE_META[role]
    msgs_key = f"chat_{role}_messages"
    partial_key = f"chat_{role}_partial"
    system_key = f"chat_{role}_system"

    if msgs_key not in st.session_state:
        st.session_state[msgs_key] = []
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
            on_click=lambda: st.session_state[msgs_key].clear(),
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
    for m in msgs:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

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
    # Evict the other role's local model; no-op when it's a cloud backend.
    other = meta["other"]
    other_ep = get_role_endpoint(config, other)
    if st.session_state.get("last_model_role") == other and not is_cloud(other_ep["backend"]):
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
        out = st.empty()
        full = ""
        error = ""
        chunk_count = 0
        usage: dict = {}
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
            )
            for token in stream:
                chunk_count += 1
                full += token
                st.session_state[partial_key] = full
                out.markdown(full + " ▌")
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
            elapsed = time.perf_counter() - start
            stats = []
            if elapsed > 0:
                stats.append(
                    f"~{chunk_count} tokens in {elapsed:.1f}s "
                    f"({chunk_count / elapsed:.1f} tok/s)"
                )
            if usage.get("input_tokens") is not None or usage.get("output_tokens") is not None:
                stats.append(
                    f"{usage.get('input_tokens', '?')} in / "
                    f"{usage.get('output_tokens', '?')} out tokens"
                )
                cost = estimate_cost(
                    model, usage.get("input_tokens"), usage.get("output_tokens")
                )
                if cost is not None:
                    stats.append(f"~${cost:.4f} est.")
            if stats:
                st.caption(" · ".join(stats))

    msgs.append({"role": "assistant", "content": full})
    st.session_state.pop(partial_key, None)
    stop_slot.empty()
