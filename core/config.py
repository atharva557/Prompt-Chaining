import copy
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
PRESETS_PATH = Path(__file__).parent.parent / "presets" / "presets.json"

def get_default_config() -> dict:
    """Return default configuration."""
    return {
        "backend": "lmstudio",           # "lmstudio" or "ollama"
        "base_url": "http://localhost:1234",
        "prompter_model": "",
        "coder_model": "",
        "output_folder": "./output",
        "prompter_temperature": 0.3,
        "coder_temperature": 0.1,
        "prompter_max_tokens": 1024,
        "coder_max_tokens": 4096,
        "custom_presets": {}
    }

def config_exists() -> bool:
    """Check if config.json exists and has the required fields."""
    if not CONFIG_PATH.exists():
        return False
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        required = ["base_url", "prompter_model", "coder_model"]
        return all(config.get(k) for k in required)
    except (json.JSONDecodeError, KeyError):
        return False

def load_config() -> dict:
    """Load config from file, merging with defaults for any missing keys."""
    defaults = get_default_config()
    if not CONFIG_PATH.exists():
        return defaults
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        defaults.update(saved)
        return defaults
    except (json.JSONDecodeError, KeyError):
        return defaults

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
    custom = config.get("custom_presets", {})

    for name, data in custom.items():
        role = data.get("role", "prompter")
        content = data.get("content", "")
        if role in presets:
            if "Custom" not in presets[role]:
                presets[role]["Custom"] = {}
            presets[role]["Custom"][name] = content

    return presets


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

