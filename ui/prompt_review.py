import difflib

import streamlit as st


def _build_diff(original: str, refined: str) -> str:
    """Unified diff between the raw idea and the refined prompt."""
    diff = difflib.unified_diff(
        original.splitlines(),
        refined.splitlines(),
        fromfile="your idea",
        tofile="refined prompt",
        lineterm="",
    )
    return "\n".join(diff)


def render_prompt_review():
    """
    Render the prompt review and edit page.
    Returns:
        'confirm' if user confirmed the prompt,
        'retry' if user wants a full regeneration from the task,
        'refine' if user wants the Prompter to revise the current prompt
            (instruction stored in st.session_state['prompt_refine_instruction']),
        None if no action taken.
    """
    st.markdown("## Review the generated prompt")
    st.markdown(
        "The Prompter model has rewritten your idea into a structured prompt. "
        "Review it below, make any edits, then send it to the Coder."
    )

    # ── Show original task ──
    with st.expander("Original task", expanded=False):
        st.markdown(f"```\n{st.session_state.get('task_description', '')}\n```")

    # ── Editable prompt ──
    edited_prompt = st.text_area(
        "Generated Prompt",
        value=st.session_state.get("generated_prompt", ""),
        height=300,
        key="prompt_review_area",
        label_visibility="collapsed"
    )

    st.caption("You can edit this prompt before sending it to the Coder model.")

    # ── Diff: what the Prompter changed ──
    with st.expander("Diff — your idea vs. refined prompt", expanded=False):
        diff_text = _build_diff(
            st.session_state.get("task_description", ""),
            edited_prompt,
        )
        if diff_text:
            st.code(diff_text, language="diff")
        else:
            st.caption("No differences.")

    # ── Revise: send the current prompt + an instruction to the Prompter ──
    st.markdown("#### Revise")
    revise_text = st.text_area(
        "Revision instruction",
        placeholder=(
            "e.g., Add keyboard controls to the requirements, drop the "
            "database part, make it shorter"
        ),
        height=80,
        key="prompt_refine_area",
        label_visibility="collapsed",
    )
    revise_clicked = st.button(
        "Revise prompt",
        key="revise_prompt_btn",
        disabled=(not revise_text or not revise_text.strip()),
        help=(
            "Sends the current prompt plus this instruction back to the "
            "Prompter, which edits it in place instead of regenerating "
            "from scratch"
        ),
    )
    if revise_clicked and revise_text and revise_text.strip():
        # Revise what's on screen, including any manual edits
        st.session_state["generated_prompt"] = edited_prompt
        st.session_state["prompt_refine_instruction"] = revise_text.strip()
        return "refine"

    # ── Action Buttons ──
    col1, col_spacer, col2 = st.columns([1, 1, 1])
    
    with col1:
        retry = st.button(
            "Try again",
            key="retry_prompt_btn",
            use_container_width=True,
            help="Regenerate the prompt from your original task"
        )
    
    with col2:
        confirm = st.button(
            "Generate code",
            key="confirm_prompt_btn",
            type="primary",
            use_container_width=True,
            help="Send this prompt to the Coder model"
        )

    if confirm:
        # Save the (possibly edited) prompt
        st.session_state["generated_prompt"] = edited_prompt
        return "confirm"
    elif retry:
        return "retry"
    
    return None
