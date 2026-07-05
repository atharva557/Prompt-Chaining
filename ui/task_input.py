import streamlit as st
from core.config import (
    get_merged_presets,
    save_custom_preset,
    capture_pipeline_profile,
    apply_pipeline_profile,
    save_pipeline_profile,
    delete_pipeline_profile,
)
from core.suggest import suggest_presets

# Default system prompts (fallbacks if presets fail to load). Kept in sync
# with "Standard Prompt Engineer" / "Clean Code" in presets/presets.json.
DEFAULT_PROMPTER_SYSTEM = """You are an expert prompt engineer specializing in prompts for coding LLMs.

Rewrite the user's rough task description into a single, detailed, well-structured prompt with these sections:

## Goal
One or two sentences stating exactly what to build.

## Tech Stack
The language/framework to use. If the user didn't specify one, choose the most natural fit and state it explicitly.

## Assumptions
Every decision the user left open (interface, storage, data shapes, styling) with the concrete default you chose — so the coder never has to guess.

## Requirements
A numbered list of concrete, testable requirements covering core functionality, inputs, and outputs.

## Edge Cases & Error Handling
The specific edge cases and failure modes the code must handle.

## Code Quality
Complete, runnable code in a single file unless the task demands otherwise; clear naming; comments only where logic is non-obvious; no placeholders or TODOs.

Rules:
- Preserve every explicit detail the user gave; never change, drop, or weaken their requirements.
- Resolve vague ideas by choosing the simplest concrete interpretation and stating it under Assumptions — never ask the user questions.
- Do not invent features beyond the reasonable scope of the request.
- Keep the prompt under ~400 words.
- Output ONLY the rewritten prompt in markdown. No preamble, no commentary, no code, no questions."""

DEFAULT_CODER_SYSTEM = """You are an expert software engineer. Implement the user's specification exactly.

Rules:
- Write complete, runnable, production-quality code — no placeholders, stubs, or omitted sections.
- Follow the specified tech stack; if unspecified, choose the most standard option and stick to it.
- If the spec is ambiguous or contradicts itself on a detail, pick the most reasonable interpretation and note it in a brief comment — never stop to ask.
- Handle the stated edge cases and add sensible error handling.
- Comment only where the logic is non-obvious.
- Output a single fenced code block containing the full solution, tagged with the language (for example ```python). No prose before or after the code block, and make sure the closing fence is present."""


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


def _render_preset_suggestion(task: str, config: dict) -> None:
    """Offer the preset pair matching the typed task, with one-click Apply.
    Purely advisory — nothing changes unless the user clicks."""
    suggestion = suggest_presets(task)
    if not suggestion:
        return
    merged = get_merged_presets(config)
    p_cat, p_name = suggestion["prompter"]
    c_cat, c_name = suggestion["coder"]
    p_text = merged.get("prompter", {}).get(p_cat, {}).get(p_name, "")
    c_text = merged.get("coder", {}).get(c_cat, {}).get(c_name, "")
    if not p_text or not c_text:
        return  # preset missing (shouldn't happen) — suggest nothing

    if (
        st.session_state.get("prompter_system") == p_text
        and st.session_state.get("coder_system") == c_text
    ):
        st.caption(f"Presets loaded for this task: **{p_name}** + **{c_name}**")
        return

    col_hint, col_apply = st.columns([4, 1])
    with col_hint:
        st.caption(
            f"This looks like {suggestion['label']} — suggested presets: "
            f"**{p_name}** (Prompter) + **{c_name}** (Coder)"
        )
    with col_apply:
        if st.button(
            "Apply",
            key="apply_suggested_presets",
            use_container_width=True,
            help="Load both suggested presets as the system prompts for this run",
        ):
            st.session_state["prompter_system"] = p_text
            st.session_state["coder_system"] = c_text
            # Drop widget state so the expander text areas pick up the new values
            st.session_state.pop("prompter_system_input", None)
            st.session_state.pop("coder_system_input", None)
            st.session_state["_preset_loaded_toast"] = (
                f"Loaded “{p_name}” + “{c_name}”"
            )
            st.rerun()


def _render_pipeline_profiles(config: dict) -> None:
    """Named snapshots of the whole pipeline setup (endpoints, sampling
    params, system prompts). Applying one rewrites config + session prompts,
    so switching e.g. 'local drafting' ↔ 'cloud final pass' is one click."""
    profiles = config.get("pipeline_profiles", {})

    with st.expander("Pipeline profiles", expanded=False):
        st.caption(
            "Save the current setup — backends, models, temperatures, and "
            "system prompts — under a name, and switch whole setups in one "
            "click (e.g. *Local drafting* vs *Cloud final pass*)."
        )

        if profiles:
            col_sel, col_apply, col_del = st.columns([3, 1, 1])
            with col_sel:
                selected = st.selectbox(
                    "Profile",
                    options=sorted(profiles),
                    key="pipeline_profile_select",
                    label_visibility="collapsed",
                )
            profile = profiles.get(selected, {})
            with col_apply:
                if st.button(
                    "Apply",
                    key="apply_pipeline_profile",
                    use_container_width=True,
                    help="Switch backends, models, params, and system prompts to this profile",
                ):
                    st.session_state["config"] = apply_pipeline_profile(config, profile)
                    for role in ("prompter", "coder"):
                        if profile.get(f"{role}_system"):
                            st.session_state[f"{role}_system"] = profile[f"{role}_system"]
                            st.session_state.pop(f"{role}_system_input", None)
                    st.session_state["_preset_loaded_toast"] = f"Applied profile “{selected}”"
                    st.rerun()
            with col_del:
                if st.button(
                    "Delete", key="delete_pipeline_profile", use_container_width=True
                ):
                    st.session_state["config"] = delete_pipeline_profile(config, selected)
                    st.rerun()
            if profile:
                st.caption(
                    f"Prompter: `{profile.get('prompter_model') or '—'}` on "
                    f"{profile.get('prompter_backend', '?')} · "
                    f"Coder: `{profile.get('coder_model') or '—'}` on "
                    f"{profile.get('coder_backend', '?')}"
                )
        else:
            st.caption("No profiles saved yet.")

        col_name, col_save = st.columns([3, 1])
        with col_name:
            new_name = st.text_input(
                "New profile name",
                key="pipeline_profile_name",
                placeholder="Name this setup, e.g. Cloud final pass",
                label_visibility="collapsed",
            )
        with col_save:
            if st.button(
                "Save current",
                key="save_pipeline_profile",
                use_container_width=True,
                disabled=not (new_name and new_name.strip()),
                help="Snapshot the current backends, models, params, and system prompts",
            ):
                profile = capture_pipeline_profile(
                    config,
                    st.session_state.get("prompter_system", DEFAULT_PROMPTER_SYSTEM),
                    st.session_state.get("coder_system", DEFAULT_CODER_SYSTEM),
                )
                st.session_state["config"] = save_pipeline_profile(
                    config, new_name.strip(), profile
                )
                st.session_state["_preset_loaded_toast"] = (
                    f"Saved profile “{new_name.strip()}”"
                )
                st.rerun()


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

    config = st.session_state.get("config", {})

    # ── Preset suggestion for the typed task ──
    if task and task.strip():
        _render_preset_suggestion(task, config)

    # ── Named pipeline profiles (apply / save / delete) ──
    _render_pipeline_profiles(config)

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
        st.toggle(
            "Quick mode — skip prompt review",
            key="quick_mode",
            help=(
                "Send the Prompter's output straight to the Coder without "
                "stopping at the Review step. You can still edit the prompt "
                "and regenerate from the output page."
            ),
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
