import os

import streamlit as st
from core.api import (
    test_connection,
    get_models,
    is_cloud,
    BACKEND_DEFAULTS,
    BACKEND_LABELS,
    ENV_KEY_NAMES,
)
from core.config import load_config, save_config

# Order shown in the backend radios: local first, then clouds
BACKEND_OPTIONS = ["lmstudio", "ollama", "custom", "openai", "anthropic", "gemini"]
PROVIDERS = ("openai", "anthropic", "gemini")


def _ensure_widget_defaults(config: dict):
    """
    Seed settings widget keys from the current config BEFORE the widgets are
    created (the Streamlit-approved pattern — never use the `value=` param).

    Keys are only initialized when missing, UNLESS _settings_just_opened is
    True (the user just navigated in), in which case everything re-syncs.
    """
    force_sync = st.session_state.pop("_settings_just_opened", False)

    defaults = {
        "settings_prompter_backend": config.get("prompter_backend", "lmstudio"),
        "settings_prompter_base_url": config.get("prompter_base_url", "http://localhost:1234"),
        "settings_coder_backend": config.get("coder_backend", "lmstudio"),
        "settings_coder_base_url": config.get("coder_base_url", "http://localhost:1234"),
        "settings_prompter_temp": config.get("prompter_temperature", 0.3),
        "settings_coder_temp": config.get("coder_temperature", 0.1),
        "settings_prompter_tokens": config.get("prompter_max_tokens", 1024),
        "settings_coder_tokens": config.get("coder_max_tokens", 4096),
        "settings_idle_unload_minutes": config.get("idle_unload_minutes", 5),
        "settings_swap_policy": config.get("swap_policy", "auto"),
        "settings_output_folder": config.get("output_folder", "./output"),
    }
    for key, value in defaults.items():
        if force_sync or key not in st.session_state:
            st.session_state[key] = value

    if force_sync:
        # Drop derived/model/key widget state so it re-initializes from config
        for role in ("prompter", "coder"):
            _clear_role_model_keys(role)
            st.session_state.pop(f"available_models_{role}", None)
            st.session_state.pop(f"_models_fetch_sig_{role}", None)
        for backend in PROVIDERS:
            st.session_state.pop(f"settings_apikey_{backend}", None)


def _clear_role_model_keys(role: str):
    """Drop a role's model picker state so it reinitializes from a fresh list."""
    for key in (f"settings_{role}_model_select", f"settings_{role}_model_input"):
        st.session_state.pop(key, None)


def _effective_key(backend: str, config: dict) -> str:
    """Resolved API key for the settings UI: env var first, then the value
    typed into (or saved for) this provider. Empty for local backends."""
    if not is_cloud(backend):
        return ""
    env_name = ENV_KEY_NAMES.get(backend)
    if env_name and os.environ.get(env_name, "").strip():
        return os.environ[env_name].strip()
    widget_key = f"settings_apikey_{backend}"
    if widget_key in st.session_state:
        return st.session_state[widget_key].strip()
    return (config.get("api_keys") or {}).get(backend, "").strip()


def _render_api_key_field(backend: str, config: dict):
    """One masked key field per cloud provider, or a notice that an
    environment variable is supplying it."""
    label = BACKEND_LABELS.get(backend, backend)
    env_name = ENV_KEY_NAMES.get(backend, "")
    if env_name and os.environ.get(env_name, "").strip():
        st.success(f"{label}: using `{env_name}` from your environment.")
        return

    widget_key = f"settings_apikey_{backend}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = (config.get("api_keys") or {}).get(backend, "")
    st.text_input(
        f"{label} API key",
        type="password",
        key=widget_key,
        placeholder=f"Paste your key (or set {env_name})" if env_name else "Paste your key",
        help="Saved to config.json (git-ignored). An environment variable takes precedence.",
    )


def _autofetch_models_for_role(role: str, base_url: str, backend: str, api_key: str) -> str:
    """
    Auto-fetch models for one role, once per (backend, url, key) combination
    so an offline/unauthenticated endpoint doesn't re-query every rerun.
    Returns an error string ("" on success or when skipped).
    """
    if is_cloud(backend) and not api_key:
        return ""  # nothing to fetch without a key — the section warns separately

    fetch_sig = f"{backend}|{base_url}|{api_key}"
    if st.session_state.get(f"available_models_{role}"):
        return ""
    if st.session_state.get(f"_models_fetch_sig_{role}") == fetch_sig:
        return st.session_state.get(f"_models_fetch_error_{role}", "")

    st.session_state[f"_models_fetch_sig_{role}"] = fetch_sig
    with st.spinner(f"Looking for {role} models..."):
        models, err = get_models(base_url, backend, api_key)

    if models:
        st.session_state[f"available_models_{role}"] = models
        st.session_state[f"_models_fetch_error_{role}"] = ""
        _clear_role_model_keys(role)
    else:
        st.session_state[f"_models_fetch_error_{role}"] = err
    return st.session_state.get(f"_models_fetch_error_{role}", "")


def _render_role_endpoint(role: str, label: str, config: dict) -> dict:
    """
    Render one role's backend / endpoint / model / params block.
    Returns {backend, base_url, model}.
    """
    st.markdown(f"### {label}")

    backend = st.radio(
        f"{label} backend",
        options=BACKEND_OPTIONS,
        format_func=lambda x: BACKEND_LABELS[x],
        horizontal=True,
        key=f"settings_{role}_backend",
        label_visibility="collapsed",
    )

    # On an actual backend switch, reset URL to that backend's default and
    # drop this role's fetched model list.
    prev = st.session_state.get(f"_settings_prev_backend_{role}")
    if prev is not None and prev != backend:
        st.session_state[f"settings_{role}_base_url"] = BACKEND_DEFAULTS.get(backend, "")
        st.session_state.pop(f"available_models_{role}", None)
        st.session_state.pop(f"_models_fetch_sig_{role}", None)
        _clear_role_model_keys(role)
    st.session_state[f"_settings_prev_backend_{role}"] = backend

    default_url = BACKEND_DEFAULTS.get(backend, "http://localhost:1234")

    if is_cloud(backend):
        # Cloud endpoints are fixed — show, don't edit
        base_url = default_url
        st.session_state[f"settings_{role}_base_url"] = default_url
        st.caption(f"Endpoint: `{default_url}`")
    else:
        base_url = st.text_input(
            f"{label} base URL",
            placeholder=default_url,
            key=f"settings_{role}_base_url",
            help=f"Default for {BACKEND_LABELS[backend]}: {default_url}",
        )
        base_url = (base_url or default_url).strip().rstrip("/")
        if backend == "custom":
            st.caption(
                "Any OpenAI-compatible server: llama.cpp, llama-swap, vLLM, "
                "Jan, KoboldCpp, TabbyAPI…"
            )

    api_key = _effective_key(backend, config)
    if is_cloud(backend) and not api_key:
        st.warning(
            f"Add your {BACKEND_LABELS[backend]} API key in the **API keys** "
            "tab to list models."
        )

    fetch_error = _autofetch_models_for_role(role, base_url, backend, api_key)

    col_test, col_refresh = st.columns(2)
    with col_test:
        if st.button("Test connection", key=f"settings_{role}_test", use_container_width=True):
            with st.spinner("Testing connection..."):
                ok, msg = test_connection(base_url, backend, api_key)
            if ok:
                st.success(msg)
                models, err = get_models(base_url, backend, api_key)
                if models:
                    st.session_state[f"available_models_{role}"] = models
                    _clear_role_model_keys(role)
                    st.rerun()
                elif err:
                    st.warning(f"Connected but couldn't fetch models: {err}")
            else:
                st.error(msg)
    with col_refresh:
        if st.button("Refresh models", key=f"settings_{role}_refresh", use_container_width=True):
            st.session_state.pop(f"available_models_{role}", None)
            st.session_state.pop(f"_models_fetch_sig_{role}", None)
            st.rerun()

    model = _render_model_picker(role, label, config, fetch_error)

    col_temp, col_tokens = st.columns(2)
    with col_temp:
        st.slider(
            f"{label} temperature",
            min_value=0.0,
            max_value=1.5,
            step=0.05,
            key=f"settings_{role}_temp",
        )
    with col_tokens:
        st.number_input(
            f"{label} max tokens",
            min_value=128,
            max_value=32768,
            step=128,
            key=f"settings_{role}_tokens",
        )

    return {"backend": backend, "base_url": base_url, "model": model}


def _render_model_picker(role: str, label: str, config: dict, fetch_error: str) -> str:
    """Dropdown when models were detected, free-text fallback otherwise."""
    available = st.session_state.get(f"available_models_{role}", [])
    saved_model = config.get(f"{role}_model", "")

    if not available:
        if fetch_error:
            st.caption(f"Couldn't list models: {fetch_error}")
        key_in = f"settings_{role}_model_input"
        if key_in not in st.session_state:
            st.session_state[key_in] = saved_model
        return st.text_input(
            f"{label} model ID",
            placeholder="Enter the model id manually",
            key=key_in,
        )

    st.caption(f"{len(available)} model(s) available.")
    key_sel = f"settings_{role}_model_select"
    if key_sel not in st.session_state:
        idx = available.index(saved_model) if saved_model in available else 0
        st.session_state[key_sel] = available[idx]
    return st.selectbox(f"{label} model", options=available, key=key_sel)


def _render_api_keys_tab(config: dict):
    """Masked key field per cloud provider (or an env-var notice)."""
    st.caption(
        "Read from environment variables first "
        "(`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`), then from "
        "here. Saved to config.json (git-ignored)."
    )
    for backend in PROVIDERS:
        _render_api_key_field(backend, config)


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

    st.markdown(
        "Configure each role independently — run both locally, or mix a local "
        "Prompter with a cloud Coder for frontier-quality code on a small GPU."
    )

    config = st.session_state.get("config", load_config())
    _ensure_widget_defaults(config)

    tab_prompter, tab_coder, tab_keys, tab_general = st.tabs(
        ["Prompter", "Coder", "API keys", "General"]
    )
    with tab_prompter:
        prompter = _render_role_endpoint("prompter", "Prompter", config)
    with tab_coder:
        coder = _render_role_endpoint("coder", "Coder", config)
    with tab_keys:
        _render_api_keys_tab(config)
    with tab_general:
        output_folder = st.text_input(
            "Output folder",
            key="settings_output_folder",
            help="Where generated code files will be saved",
        )
        st.number_input(
            "Auto-unload idle local models (minutes, 0 = never)",
            min_value=0,
            max_value=120,
            step=1,
            key="settings_idle_unload_minutes",
            help=(
                "Free local VRAM when the resident model (Prompter or Coder) "
                "has sat idle this long. Any interaction resets the timer; "
                "cloud backends are unaffected."
            ),
        )
        st.selectbox(
            "VRAM swap policy",
            options=["auto", "never"],
            format_func=lambda v: {
                "auto": "Auto — unload one model before running the other",
                "never": "Never — both models fit in VRAM at once",
            }[v],
            key="settings_swap_policy",
            help=(
                "'Auto' frees the Prompter's VRAM before the Coder runs "
                "(single-GPU default). Pick 'Never' if your GPU holds both "
                "models — it skips the unload/reload cycle entirely."
            ),
        )

    # Same local model for both roles defeats the VRAM swap
    if (
        prompter["model"]
        and prompter["model"] == coder["model"]
        and prompter["backend"] == coder["backend"]
    ):
        st.warning(
            "Both roles use the same model on the same backend. This works, "
            "but different models are recommended."
        )

    # ── Save ──
    st.markdown("---")
    if st.button("Save settings", key="save_settings_btn", type="primary", use_container_width=True):
        # Preserve saved keys for providers not rendered (env-supplied or
        # unselected); overwrite only fields the user actually edited.
        saved_keys = {"openai": "", "anthropic": "", "gemini": ""}
        saved_keys.update(config.get("api_keys") or {})
        for backend in PROVIDERS:
            widget_key = f"settings_apikey_{backend}"
            if widget_key in st.session_state:
                saved_keys[backend] = st.session_state[widget_key].strip()

        new_config = {
            "prompter_backend": prompter["backend"],
            "prompter_base_url": prompter["base_url"],
            "coder_backend": coder["backend"],
            "coder_base_url": coder["base_url"],
            "prompter_model": prompter["model"],
            "coder_model": coder["model"],
            "api_keys": saved_keys,
            "output_folder": output_folder,
            "prompter_temperature": st.session_state["settings_prompter_temp"],
            "coder_temperature": st.session_state["settings_coder_temp"],
            "prompter_max_tokens": st.session_state["settings_prompter_tokens"],
            "coder_max_tokens": st.session_state["settings_coder_tokens"],
            "idle_unload_minutes": st.session_state["settings_idle_unload_minutes"],
            "swap_policy": st.session_state["settings_swap_policy"],
            "pipeline_profiles": config.get("pipeline_profiles", {}),
            "custom_presets": config.get("custom_presets", {}),
            "preset_overrides": config.get("preset_overrides", {}),
        }
        save_config(new_config)
        st.session_state["config"] = new_config

        if prompter["model"] and coder["model"]:
            st.session_state["show_settings"] = False
            st.session_state["_settings_saved_toast"] = True
            st.rerun()
        else:
            st.warning("Saved, but both models must be set before you can leave Settings.")
