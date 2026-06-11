import streamlit as st
from core.api import test_connection, get_models, BACKEND_DEFAULTS, BACKEND_LABELS
from core.config import load_config, save_config


def _ensure_widget_defaults(config: dict):
    """
    Ensure all settings widget keys exist in session state with values
    from the current config. This is the Streamlit-approved pattern:
    set session state BEFORE widget creation, never use `value=` param.

    Only initializes keys that don't already exist, UNLESS
    _settings_just_opened is True (user navigated to settings).
    """
    force_sync = st.session_state.pop("_settings_just_opened", False)

    defaults = {
        "settings_backend": config.get("backend", "lmstudio"),
        "settings_base_url": config.get("base_url", "http://localhost:1234"),
        "settings_prompter_temp": config.get("prompter_temperature", 0.3),
        "settings_coder_temp": config.get("coder_temperature", 0.1),
        "settings_prompter_tokens": config.get("prompter_max_tokens", 1024),
        "settings_coder_tokens": config.get("coder_max_tokens", 4096),
        "settings_output_folder": config.get("output_folder", "./output"),
    }

    for key, value in defaults.items():
        if force_sync or key not in st.session_state:
            st.session_state[key] = value

    # Always clear model widget keys on force sync so they
    # re-initialize from config with correct index
    if force_sync:
        for key in [
            "settings_prompter_model_input",
            "settings_coder_model_input",
            "settings_prompter_model_select",
            "settings_coder_model_select",
        ]:
            if key in st.session_state:
                del st.session_state[key]


def _clear_model_select_keys():
    """Drop model selectbox state so it reinitializes from a fresh model list."""
    for key in ["settings_prompter_model_select", "settings_coder_model_select"]:
        if key in st.session_state:
            del st.session_state[key]


def _autofetch_models(base_url: str, backend: str):
    """
    Automatically fetch installed models for the current backend/URL.
    Attempted once per (backend, url) combination so an offline server
    doesn't hang the page on every rerun. Returns an error string ("" if ok).
    """
    fetch_sig = f"{backend}|{base_url}"
    if st.session_state.get("available_models"):
        return ""
    if st.session_state.get("_models_fetch_sig") == fetch_sig:
        return st.session_state.get("_models_fetch_error", "")

    st.session_state["_models_fetch_sig"] = fetch_sig
    with st.spinner("Looking for installed models..."):
        models, err = get_models(base_url, backend)

    if models:
        st.session_state["available_models"] = models
        st.session_state["_models_fetch_error"] = ""
        _clear_model_select_keys()
    else:
        st.session_state["_models_fetch_error"] = err
    return st.session_state["_models_fetch_error"]


def render_settings():
    """Render the settings configuration page."""

    # ── Back navigation (no trap: always one click back to the app) ──
    col_back, col_title = st.columns([1, 5])
    with col_back:
        if st.button("← Back", key="settings_back_btn", use_container_width=True):
            st.session_state["show_settings"] = False
            st.rerun()
    with col_title:
        st.markdown("## Settings")

    st.markdown("Configure your LLM server connection and model preferences.")
    st.markdown("---")

    config = st.session_state.get("config", load_config())

    # Initialize widget keys from config (avoids the value=/key= conflict)
    _ensure_widget_defaults(config)

    # ── Backend Selection ──
    st.markdown("### Backend")
    backend_options = ["lmstudio", "ollama", "custom"]
    backend_labels = BACKEND_LABELS

    selected_backend = st.radio(
        "Select your LLM backend",
        options=backend_options,
        format_func=lambda x: backend_labels[x],
        horizontal=True,
        key="settings_backend",
    )

    if selected_backend == "custom":
        st.caption(
            "Any OpenAI-compatible server: llama.cpp server, llama-swap, "
            "vLLM, Jan, KoboldCpp, TabbyAPI… Model listing uses `/v1/models`; "
            "model unloading is left to the server (e.g. llama-swap's TTL)."
        )

    # On an actual backend switch (not every rerun), reset URL to that
    # backend's default and clear the fetched model list
    prev_backend = st.session_state.get("_settings_prev_backend")
    if prev_backend is not None and prev_backend != selected_backend:
        st.session_state["settings_base_url"] = BACKEND_DEFAULTS.get(
            selected_backend, "http://localhost:1234"
        )
        st.session_state["available_models"] = []
        st.session_state.pop("_models_fetch_sig", None)
        _clear_model_select_keys()
    st.session_state["_settings_prev_backend"] = selected_backend

    default_url = BACKEND_DEFAULTS.get(selected_backend, "http://localhost:1234")

    st.markdown("### Server connection")
    base_url = st.text_input(
        "Base URL",
        placeholder=default_url,
        key="settings_base_url",
        help=f"Default for {backend_labels[selected_backend]}: {default_url}",
    )
    base_url = (base_url or default_url).strip().rstrip("/")

    # ── Auto-detect installed models (works for LM Studio AND Ollama) ──
    fetch_error = _autofetch_models(base_url, selected_backend)

    col_test, col_refresh, col_status = st.columns([1, 1, 2])
    with col_test:
        test_clicked = st.button(
            "Test connection",
            key="test_connection_btn",
            use_container_width=True,
        )
    with col_refresh:
        if st.button("Refresh models", key="refresh_models_btn", use_container_width=True):
            # Reset the autofetch guard so the next run re-queries the server
            st.session_state["available_models"] = []
            st.session_state.pop("_models_fetch_sig", None)
            st.rerun()

    if test_clicked:
        with st.spinner("Testing connection..."):
            success, message = test_connection(base_url, selected_backend)
        if success:
            st.success(message)
            models, err = get_models(base_url, selected_backend)
            if models:
                st.session_state["available_models"] = models
                _clear_model_select_keys()
                st.rerun()
            elif err:
                st.warning(f"Connected but couldn't fetch models: {err}")
        else:
            st.error(message)

    # ── Model Selection ──
    st.markdown("### Models")

    available_models = st.session_state.get("available_models", [])

    if not available_models:
        if fetch_error:
            st.warning(
                f"Couldn't detect installed models: {fetch_error} "
                "Start your server and click **Refresh models**, "
                "or enter the model IDs manually below."
            )
        else:
            st.info("No models detected. Click **Refresh models** or enter IDs manually.")

        # Initialize model text input keys if not set
        if "settings_prompter_model_input" not in st.session_state:
            st.session_state["settings_prompter_model_input"] = config.get("prompter_model", "")
        if "settings_coder_model_input" not in st.session_state:
            st.session_state["settings_coder_model_input"] = config.get("coder_model", "")

        prompter_model = st.text_input(
            "Prompter Model ID",
            placeholder="e.g., phi-4-mini-reasoning",
            key="settings_prompter_model_input",
        )
        coder_model = st.text_input(
            "Coder Model ID",
            placeholder="e.g., qwen2.5-coder-14b-instruct",
            key="settings_coder_model_input",
        )
    else:
        st.caption(f"{len(available_models)} installed model(s) detected.")

        # Dropdown selection from fetched models
        prompter_idx = 0
        if config.get("prompter_model") in available_models:
            prompter_idx = available_models.index(config["prompter_model"])

        coder_idx = (
            min(1, len(available_models) - 1) if len(available_models) > 1 else 0
        )
        if config.get("coder_model") in available_models:
            coder_idx = available_models.index(config["coder_model"])

        # Initialize selectbox keys if not already set
        if "settings_prompter_model_select" not in st.session_state:
            st.session_state["settings_prompter_model_select"] = (
                available_models[prompter_idx] if available_models else None
            )
        if "settings_coder_model_select" not in st.session_state:
            st.session_state["settings_coder_model_select"] = (
                available_models[coder_idx] if available_models else None
            )

        prompter_model = st.selectbox(
            "Prompter Model (small, fast reasoning)",
            options=available_models,
            key="settings_prompter_model_select",
        )

        coder_model = st.selectbox(
            "Coder Model (larger, coding-focused)",
            options=available_models,
            key="settings_coder_model_select",
        )

    # Warning for same model
    if prompter_model and coder_model and prompter_model == coder_model:
        st.warning(
            "You've selected the same model for both roles. "
            "This works, but using different models is recommended."
        )

    # ── Advanced Settings ──
    st.markdown("### Generation parameters")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Prompter**")
        prompter_temp = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=1.5,
            step=0.05,
            key="settings_prompter_temp",
            help="Lower = more focused, Higher = more creative",
        )
        prompter_max_tokens = st.number_input(
            "Max Tokens",
            min_value=128,
            max_value=8192,
            step=128,
            key="settings_prompter_tokens",
        )

    with col2:
        st.markdown("**Coder**")
        coder_temp = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=1.5,
            step=0.05,
            key="settings_coder_temp",
            help="Lower = more deterministic code",
        )
        coder_max_tokens = st.number_input(
            "Max Tokens",
            min_value=128,
            max_value=16384,
            step=256,
            key="settings_coder_tokens",
        )

    # ── Output Folder ──
    st.markdown("### Output")
    output_folder = st.text_input(
        "Output folder",
        key="settings_output_folder",
        help="Where generated code files will be saved",
    )

    # ── Save Button ──
    st.markdown("---")
    if st.button(
        "Save settings",
        key="save_settings_btn",
        type="primary",
        use_container_width=True,
    ):
        new_config = {
            "backend": selected_backend,
            "base_url": base_url,
            "prompter_model": prompter_model,
            "coder_model": coder_model,
            "output_folder": output_folder,
            "prompter_temperature": prompter_temp,
            "coder_temperature": coder_temp,
            "prompter_max_tokens": prompter_max_tokens,
            "coder_max_tokens": coder_max_tokens,
            "custom_presets": config.get("custom_presets", {}),
        }
        save_config(new_config)
        st.session_state["config"] = new_config

        if prompter_model and coder_model:
            # Return to the app automatically — no dead end after saving
            st.session_state["show_settings"] = False
            st.session_state["_settings_saved_toast"] = True
            st.rerun()
        else:
            st.warning("Saved, but both models must be set before you can leave Settings.")
