import streamlit as st
from core.config import get_merged_presets, save_custom_preset

# Default system prompts (fallbacks if presets fail to load)
DEFAULT_PROMPTER_SYSTEM = """You are an expert prompt engineer specializing in prompts for coding LLMs.

Rewrite the user's rough task description into a single, detailed, well-structured prompt with these sections:

## Goal
One or two sentences stating exactly what to build.

## Tech Stack
The language/framework to use. If the user didn't specify one, choose the most natural fit and state it explicitly.

## Requirements
A numbered list of concrete, testable requirements covering core functionality, inputs, and outputs.

## Edge Cases & Error Handling
The specific edge cases and failure modes the code must handle.

## Code Quality
Complete, runnable code in a single file unless the task demands otherwise; clear naming; comments only where logic is non-obvious; no placeholders or TODOs.

Rules:
- Preserve every explicit detail the user gave; never change or drop their requirements.
- Do not invent features beyond the reasonable scope of the request.
- Keep the prompt under ~400 words.
- Output ONLY the rewritten prompt in markdown. No preamble, no commentary, no code."""

DEFAULT_CODER_SYSTEM = """You are an expert software engineer. Implement the user's specification exactly.

Rules:
- Write complete, runnable, production-quality code — no placeholders, stubs, or omitted sections.
- Follow the specified tech stack; if unspecified, choose the most standard option and stick to it.
- Handle the stated edge cases and add sensible error handling.
- Comment only where the logic is non-obvious.
- Output a single fenced code block containing the full solution, tagged with the language (for example ```python). No prose before or after the code block."""


def _render_preset_selector(role: str, label: str, config: dict) -> None:
    """
    Render a preset selector (category + preset dropdowns + load button)
    for either the prompter or coder role. Loading a preset writes it to
    st.session_state[f"{role}_system"] and reruns.

    Args:
        role: 'prompter' or 'coder'
        label: Display label (e.g., 'Prompter' or 'Coder')
        config: Current app config dict
    """
    presets = get_merged_presets(config)
    role_presets = presets.get(role, {})

    if not role_presets:
        st.caption("No presets available.")
        return

    # Category dropdown
    categories = list(role_presets.keys())
    selected_category = st.selectbox(
        f"Category",
        options=categories,
        key=f"preset_category_{role}",
        label_visibility="collapsed",
        help=f"Select a preset category for the {label}",
    )

    # Preset name dropdown (filtered by category)
    if selected_category and selected_category in role_presets:
        preset_names = list(role_presets[selected_category].keys())
        if preset_names:
            selected_preset = st.selectbox(
                f"Preset",
                options=preset_names,
                key=f"preset_name_{role}",
                label_visibility="collapsed",
            )

            # Load preset button
            if st.button(
                "Load preset",
                key=f"load_preset_{role}",
                use_container_width=True,
            ):
                preset_content = role_presets[selected_category][selected_preset]
                st.session_state[f"{role}_system"] = preset_content
                # Clear the text area widget key so it picks up the new value
                widget_key = f"{role}_system_input"
                if widget_key in st.session_state:
                    del st.session_state[widget_key]
                # Confirmation shown after the rerun (see app.py toast area)
                st.session_state["_preset_loaded_toast"] = (
                    f"Loaded “{selected_preset}” as the {label} prompt"
                )
                st.rerun()


def _render_save_custom_preset(role: str, label: str, prompt_text: str, config: dict):
    """Render the 'Save as Custom Preset' UI for a given role."""
    with st.popover("Save as custom preset", use_container_width=True):
        st.markdown(f"**Save current {label} prompt as a custom preset**")
        preset_name = st.text_input(
            "Preset name",
            placeholder=f"e.g., My {label} Preset",
            key=f"custom_preset_name_{role}",
        )
        if st.button(
            "Save Preset",
            key=f"save_custom_preset_{role}",
            type="primary",
            use_container_width=True,
            disabled=(not preset_name or not preset_name.strip()),
        ):
            updated_config = save_custom_preset(
                config, preset_name.strip(), role, prompt_text
            )
            st.session_state["config"] = updated_config
            st.success(f"Saved '{preset_name.strip()}'")


def render_task_input():
    """Render the task description input page."""
    st.markdown("## What do you want to build?")
    st.markdown(
        "Describe your idea in plain English. The Prompter model will "
        "turn it into a detailed, structured prompt for the Coder."
    )

    # ── Task Description ──
    task = st.text_area(
        "Your idea",
        value=st.session_state.get("task_description", ""),
        height=150,
        placeholder=(
            "Examples:\n"
            "• A React calculator with keyboard support\n"
            "• A Python script that monitors a folder for new files\n"
            "• A FastAPI REST API for a todo list\n"
            "• A CLI tool that converts CSV to JSON"
        ),
        key="task_input_area",
        label_visibility="collapsed",
    )

    # ── System Prompts with Preset Selectors ──
    config = st.session_state.get("config", {})

    with st.expander("System prompts & presets", expanded=False):
        st.markdown(
            "Choose a preset or customize the instructions given to each model."
        )

        col1, col2 = st.columns(2)

        # ── Prompter Column ──
        with col1:
            st.markdown("**Prompter system prompt**")

            # Preset selector
            _render_preset_selector(role="prompter", label="Prompter", config=config)

            st.markdown("")  # spacing

            # Editable text area
            prompter_system = st.text_area(
                "Prompter instructions",
                value=st.session_state.get(
                    "prompter_system", DEFAULT_PROMPTER_SYSTEM
                ),
                height=200,
                key="prompter_system_input",
                label_visibility="collapsed",
            )

            # Save as custom preset
            _render_save_custom_preset("prompter", "Prompter", prompter_system, config)

        # ── Coder Column ──
        with col2:
            st.markdown("**Coder system prompt**")

            # Preset selector
            _render_preset_selector(role="coder", label="Coder", config=config)

            st.markdown("")  # spacing

            # Editable text area
            coder_system = st.text_area(
                "Coder instructions",
                value=st.session_state.get("coder_system", DEFAULT_CODER_SYSTEM),
                height=200,
                key="coder_system_input",
                label_visibility="collapsed",
            )

            # Save as custom preset
            _render_save_custom_preset("coder", "Coder", coder_system, config)

        # Save system prompts to session state
        st.session_state["prompter_system"] = prompter_system
        st.session_state["coder_system"] = coder_system

    # ── Generate Button ──
    st.markdown("")
    col_left, col_center, col_right = st.columns([1, 2, 1])
    with col_center:
        generate_clicked = st.button(
            "Generate prompt",
            key="generate_prompt_btn",
            type="primary",
            use_container_width=True,
            disabled=(not task or not task.strip()),
        )

    if generate_clicked and task and task.strip():
        st.session_state["task_description"] = task.strip()
        # Ensure system prompts are set
        if "prompter_system" not in st.session_state:
            st.session_state["prompter_system"] = DEFAULT_PROMPTER_SYSTEM
        if "coder_system" not in st.session_state:
            st.session_state["coder_system"] = DEFAULT_CODER_SYSTEM
        return True  # Signal to app.py to run the prompter

    return False
