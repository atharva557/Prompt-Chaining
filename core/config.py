import copy
import json
import os
from pathlib import Path

from core.api import BACKEND_DEFAULTS, ENV_KEY_NAMES

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
PRESETS_PATH = Path(__file__).parent.parent / "presets" / "presets.json"

def get_default_config() -> dict:
    """
    Return default configuration.

    Backend/base_url are per-role so the Prompter and Coder can run on
    different backends (e.g. local Prompter + cloud Coder). API keys for the
    cloud providers live under `api_keys` (env vars take precedence at use).
    """
    return {
        "prompter_backend": "lmstudio",
        "prompter_base_url": "http://localhost:1234",
        "coder_backend": "lmstudio",
        "coder_base_url": "http://localhost:1234",
        "prompter_model": "",
        "coder_model": "",
        "api_keys": {"openai": "", "anthropic": "", "gemini": ""},
        "output_folder": "./output",
        "prompter_temperature": 0.3,
        "coder_temperature": 0.1,
        "prompter_max_tokens": 1024,
        "coder_max_tokens": 4096,
        # Free a resident local model's VRAM after this many idle minutes;
        # 0 = never. Applies to whichever role (prompter or coder) served last.
        "idle_unload_minutes": 5,
        # 'auto' unloads one local model before running the other (single-GPU
        # default); 'never' skips all cross-role unloads for machines whose
        # VRAM fits both models at once.
        "swap_policy": "auto",
        # Named snapshots of a full pipeline setup (endpoints, sampling params,
        # system prompts) that can be applied in one click from the task page.
        "pipeline_profiles": {},
        "custom_presets": {},
        # Edits to built-in presets, keyed role -> category -> name -> text.
        # Kept separate so the shipped presets.json is never mutated.
        "preset_overrides": {},
    }


def _migrate_config(saved: dict) -> dict:
    """Backfill the per-role schema from a legacy single-backend config so
    existing users upgrade seamlessly."""
    saved = dict(saved)
    legacy_backend = saved.get("backend")
    legacy_url = saved.get("base_url")
    if "prompter_backend" not in saved and legacy_backend:
        saved["prompter_backend"] = legacy_backend
        saved["coder_backend"] = legacy_backend
    if "prompter_base_url" not in saved and legacy_url:
        saved["prompter_base_url"] = legacy_url
        saved["coder_base_url"] = legacy_url
    if "api_keys" not in saved:
        saved["api_keys"] = {"openai": "", "anthropic": "", "gemini": ""}
    # The idle-unload setting was briefly coder-only before covering both roles
    if "idle_unload_minutes" not in saved and "coder_idle_unload_minutes" in saved:
        saved["idle_unload_minutes"] = saved["coder_idle_unload_minutes"]
    return saved


def config_exists() -> bool:
    """Check if config.json exists and has both models plus endpoint info
    (tolerant of both the per-role and the legacy single-backend schema)."""
    if not CONFIG_PATH.exists():
        return False
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return False
    if not (config.get("prompter_model") and config.get("coder_model")):
        return False
    has_per_role = config.get("prompter_base_url") and config.get("coder_base_url")
    has_legacy = bool(config.get("base_url"))
    return bool(has_per_role or has_legacy)

def load_config() -> dict:
    """Load config from file, migrating legacy schema and merging with
    defaults for any missing keys."""
    defaults = get_default_config()
    if not CONFIG_PATH.exists():
        return defaults
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return defaults
    defaults.update(_migrate_config(saved))
    return defaults


def _resolve_api_key(config: dict, backend: str) -> str:
    """API key for a cloud backend: environment variable first, then the
    key saved in config.json. Empty string for local backends."""
    env_name = ENV_KEY_NAMES.get(backend)
    if env_name:
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            return env_val
    return (config.get("api_keys") or {}).get(backend, "")


def get_role_endpoint(config: dict, role: str) -> dict:
    """
    Resolve the active endpoint for 'prompter' or 'coder'.
    Returns {backend, base_url, model, api_key} — the single seam every
    generation call site uses instead of reading config keys directly.
    """
    backend = config.get(f"{role}_backend", "lmstudio")
    base_url = config.get(f"{role}_base_url") or BACKEND_DEFAULTS.get(backend, "")
    return {
        "backend": backend,
        "base_url": base_url,
        "model": config.get(f"{role}_model", ""),
        "api_key": _resolve_api_key(config, backend),
    }

def swap_enabled(config: dict) -> bool:
    """False when the user opted out of VRAM swapping ('never' policy —
    both models fit in VRAM, so cross-role unloads are pure overhead)."""
    return config.get("swap_policy", "auto") != "never"


def save_config(config: dict) -> None:
    """
    Save config dict to config.json.

    Note: config.json is shared across browser tabs/sessions; concurrent
    saves are last-writer-wins. Acceptable for a single-user local app.
    """
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# ═══════════════════════════════════════════════════════
#  Pipeline Profiles
# ═══════════════════════════════════════════════════════

# Config keys snapshotted into (and restored from) a pipeline profile —
# everything that defines "which two models run and how", so switching e.g.
# "local drafting" ↔ "cloud final pass" is one click instead of a Settings trip.
PROFILE_CONFIG_KEYS = (
    "prompter_backend", "prompter_base_url", "prompter_model",
    "coder_backend", "coder_base_url", "coder_model",
    "prompter_temperature", "coder_temperature",
    "prompter_max_tokens", "coder_max_tokens",
)


def capture_pipeline_profile(config: dict, prompter_system: str, coder_system: str) -> dict:
    """Snapshot the current endpoints/params plus the active system prompts."""
    profile = {key: config.get(key) for key in PROFILE_CONFIG_KEYS}
    profile["prompter_system"] = prompter_system
    profile["coder_system"] = coder_system
    return profile


def apply_pipeline_profile(config: dict, profile: dict) -> dict:
    """Write a profile's endpoint/param snapshot into the config and persist
    it. System prompts are returned to the caller via the profile itself —
    they live in session state, not config."""
    for key in PROFILE_CONFIG_KEYS:
        if profile.get(key) is not None:
            config[key] = profile[key]
    save_config(config)
    return config


def save_pipeline_profile(config: dict, name: str, profile: dict) -> dict:
    """Create or overwrite a named pipeline profile."""
    config.setdefault("pipeline_profiles", {})[name] = profile
    save_config(config)
    return config


def delete_pipeline_profile(config: dict, name: str) -> dict:
    """Remove a named pipeline profile (no-op if absent)."""
    profiles = config.get("pipeline_profiles", {})
    if name in profiles:
        del profiles[name]
        save_config(config)
    return config


# ═══════════════════════════════════════════════════════
#  Preset Management
# ═══════════════════════════════════════════════════════

# Module-level cache keyed by file mtime: presets.json is otherwise re-read
# and re-parsed on every Streamlit rerun. Kept here (not st.cache_data) so
# core/ stays free of streamlit imports; manual edits to the file are still
# picked up via the mtime check.
_presets_cache: dict | None = None
_presets_mtime: float = -1.0


def load_presets() -> dict:
    """
    Load built-in presets from presets/presets.json (cached by mtime).
    Returns dict with 'prompter' and 'coder' keys, each containing
    category -> preset_name -> prompt_text mappings.
    """
    global _presets_cache, _presets_mtime

    if not PRESETS_PATH.exists():
        return {"prompter": {}, "coder": {}}

    try:
        mtime = PRESETS_PATH.stat().st_mtime
        if _presets_cache is None or mtime != _presets_mtime:
            _presets_cache = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
            _presets_mtime = mtime
        # Copy so callers (get_merged_presets) can't mutate the cache
        return copy.deepcopy(_presets_cache)
    except (json.JSONDecodeError, KeyError, OSError):
        return {"prompter": {}, "coder": {}}


def get_merged_presets(config: dict) -> dict:
    """
    Merge built-in presets with user's custom presets from config.
    Custom presets are added under a 'Custom' category for each role.

    Returns dict like:
    {
        "prompter": {
            "General": {"Standard Prompt Engineer": "..."},
            "Custom": {"My Custom Preset": "..."}
        },
        "coder": { ... }
    }
    """
    presets = load_presets()

    # Apply edits to built-in presets (only when the built-in still exists, so
    # stale overrides for removed presets are silently ignored).
    overrides = config.get("preset_overrides", {})
    for role, categories in overrides.items():
        for category, names in categories.items():
            for name, content in names.items():
                if name in presets.get(role, {}).get(category, {}):
                    presets[role][category][name] = content

    custom = config.get("custom_presets", {})
    for name, data in custom.items():
        role = data.get("role", "prompter")
        content = data.get("content", "")
        if role in presets:
            if "Custom" not in presets[role]:
                presets[role]["Custom"] = {}
            presets[role]["Custom"][name] = content

    return presets


def is_preset_overridden(config: dict, role: str, category: str, name: str) -> bool:
    """True when a built-in preset has a saved user edit."""
    return name in config.get("preset_overrides", {}).get(role, {}).get(category, {})


def save_preset_override(config: dict, role: str, category: str, name: str, content: str) -> dict:
    """Save an edit to a built-in preset (does not touch presets.json)."""
    overrides = config.setdefault("preset_overrides", {})
    overrides.setdefault(role, {}).setdefault(category, {})[name] = content
    save_config(config)
    return config


def reset_preset_override(config: dict, role: str, category: str, name: str) -> dict:
    """Remove a built-in preset edit, restoring the shipped default."""
    overrides = config.get("preset_overrides", {})
    role_ov = overrides.get(role, {})
    cat_ov = role_ov.get(category, {})
    if name in cat_ov:
        del cat_ov[name]
        if not cat_ov:
            del role_ov[category]
        if not role_ov:
            del overrides[role]
        save_config(config)
    return config


def save_custom_preset(config: dict, name: str, role: str, content: str) -> dict:
    """
    Save a custom preset to config.json.
    Returns the updated config dict.
    """
    if "custom_presets" not in config:
        config["custom_presets"] = {}

    config["custom_presets"][name] = {
        "role": role,
        "content": content,
    }
    save_config(config)
    return config


def delete_custom_preset(config: dict, name: str) -> dict:
    """
    Delete a custom preset from config.json.
    Returns the updated config dict.
    """
    if "custom_presets" in config and name in config["custom_presets"]:
        del config["custom_presets"][name]
        save_config(config)
    return config

