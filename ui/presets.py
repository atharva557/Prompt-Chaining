"""
PromptChain — Presets Manager

Browse every system-prompt preset (built-in + custom) for both roles, edit any
of them, reset edited built-ins to their shipped default, and create or delete
custom presets. Edits to built-ins are stored as overrides in config.json, so
the shipped presets/presets.json is never mutated.
"""

import streamlit as st

from core.config import (
    get_merged_presets,
    is_preset_overridden,
    save_preset_override,
    reset_preset_override,
    save_custom_preset,
    delete_custom_preset,
    load_presets,
)

ROLE_LABELS = {"prompter": "Prompter", "coder": "Coder"}


def _set_config(config: dict):
    st.session_state["config"] = config


def _render_preset_card(role: str, category: str, name: str, content: str, config: dict):
    """One editable preset, with Save + Reset/Delete actions."""
    is_custom = category == "Custom"
    overridden = (not is_custom) and is_preset_overridden(config, role, category, name)
    in_use = content == st.session_state.get(f"{role}_system", "")
    badge = " · custom" if is_custom else (" · edited" if overridden else "")
    if in_use:
        badge += " · in use"

    with st.expander(f"{name}{badge}"):
        widget_key = f"presetmgr_{role}_{category}_{name}"
        edited = st.text_area(
            "Preset content",
            value=content,
            height=240,
            key=widget_key,
            label_visibility="collapsed",
        )
        col_save, col_other = st.columns(2)

        with col_save:
            if st.button("Save", key=f"save_{widget_key}", use_container_width=True, type="primary"):
                if is_custom:
                    _set_config(save_custom_preset(config, name, role, edited))
                else:
                    _set_config(save_preset_override(config, role, category, name, edited))
                st.session_state["_preset_toast"] = f"Saved “{name}”"
                st.rerun()

        with col_other:
            if is_custom:
                if st.button("Delete", key=f"del_{widget_key}", use_container_width=True):
                    _set_config(delete_custom_preset(config, name))
                    st.session_state.pop(widget_key, None)
                    st.session_state["_preset_toast"] = f"Deleted “{name}”"
                    st.rerun()
            else:
                if st.button(
                    "Reset to default",
                    key=f"reset_{widget_key}",
                    use_container_width=True,
                    disabled=not overridden,
                    help="Restore the shipped default for this built-in preset",
                ):
                    _set_config(reset_preset_override(config, role, category, name))
                    # Drop widget state so the box re-initializes from the default
                    st.session_state.pop(widget_key, None)
                    st.session_state["_preset_toast"] = f"Reset “{name}” to default"
                    st.rerun()


def _render_new_preset_form(role: str, config: dict):
    """Create a new custom preset for this role (lands under the Custom category)."""
    with st.expander("➕ New custom preset"):
        name = st.text_input(
            "Name",
            key=f"new_preset_name_{role}",
            placeholder=f"e.g., My {ROLE_LABELS[role]} Style",
        )
        content = st.text_area(
            "Instructions",
            key=f"new_preset_content_{role}",
            height=200,
            placeholder="The system prompt for this preset…",
        )
        valid = bool(name and name.strip() and content and content.strip())
        if st.button(
            "Create preset",
            key=f"create_preset_{role}",
            type="primary",
            disabled=not valid,
        ):
            _set_config(save_custom_preset(config, name.strip(), role, content))
            st.session_state.pop(f"new_preset_name_{role}", None)
            st.session_state.pop(f"new_preset_content_{role}", None)
            st.session_state["_preset_toast"] = f"Created “{name.strip()}”"
            st.rerun()


def _render_role_presets(role: str, config: dict):
    merged = get_merged_presets(config)
    role_presets = merged.get(role, {})
    builtins = load_presets().get(role, {})

    n_builtin = sum(len(v) for k, v in role_presets.items() if k != "Custom")
    n_custom = len(role_presets.get("Custom", {}))
    st.caption(f"{n_builtin} built-in · {n_custom} custom")

    _render_new_preset_form(role, config)

    # Built-in categories first (in shipped order), then Custom last
    ordered = [c for c in builtins.keys() if c in role_presets]
    if "Custom" in role_presets:
        ordered.append("Custom")

    for category in ordered:
        st.markdown(f"#### {category}")
        for name, content in role_presets[category].items():
            _render_preset_card(role, category, name, content, config)


def render_presets_manager(config: dict) -> None:
    """Render the full presets manager page."""
    toast = st.session_state.pop("_preset_toast", "")
    if toast:
        st.toast(toast)

    col_back, col_title = st.columns([1, 5])
    with col_back:
        if st.button("← Back", key="presets_back_btn", use_container_width=True):
            st.session_state["page"] = "landing"
            st.rerun()
    with col_title:
        st.markdown("## Presets")

    st.markdown(
        "Browse and edit the system prompts each model uses. Edits to built-in "
        "presets can be reset to their default; custom presets can be deleted."
    )

    tab_prompter, tab_coder = st.tabs(["Prompter", "Coder"])
    with tab_prompter:
        _render_role_presets("prompter", config)
    with tab_coder:
        _render_role_presets("coder", config)
