"""endpoints.toml — the model registry used by the MCP server (and CLI).

The library API itself is file-free (you construct Endpoints in code); this
module exists for the entry points that need configuration *outside* Python:
an agent's MCP config can't build objects, so it points at a small TOML file
in the user's config directory instead::

    [manager]
    policy = "auto"          # or "manual"
    max_resident = 1
    idle_unload = 0          # seconds; 0 = never

    [models.coder]
    backend = "ollama"       # lmstudio | ollama | custom | openai | anthropic | gemini
    base_url = "http://localhost:11434"
    model = "qwen3-coder:30b"
    priority = 10
    pinned = false
    # idle_unload = 300      # per-model override
    # vram_hint = "18GiB"    # for vram_budget accounting

API keys are deliberately NOT written here — cloud endpoints read them from
environment variables (OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY);
an explicit `api_key` field is honored if the user adds one by hand.

On first run the file is seeded from the PromptChain app's config.json
(prompter/coder roles) when one is found in the working directory, otherwise
a commented template with the stock local servers is written.
"""

import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

import platformdirs

from .backends import BACKEND_DEFAULTS
from .endpoint import Endpoint
from .manager import ModelManager

APP_NAME = "promptchain"


def default_config_path() -> Path:
    """~/.config/promptchain/endpoints.toml (per-OS via platformdirs)."""
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "endpoints.toml"


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dump_toml(manager: dict, models: dict[str, dict]) -> str:
    """Minimal TOML writer for our flat two-level structure."""
    lines = [
        "# promptchain endpoints — read by `promptchain-mcp` (and the CLI).",
        "# API keys are read from env vars (OPENAI_API_KEY / ANTHROPIC_API_KEY /",
        "# GEMINI_API_KEY); add api_key = \"...\" to a model only if you must.",
        "",
        "[manager]",
    ]
    for key, value in manager.items():
        lines.append(f"{key} = {_toml_value(value)}")
    for name, fields in models.items():
        lines += ["", f"[models.{name}]"]
        for key, value in fields.items():
            if value is None or value == "":
                continue
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def seed_from_app_config(app_config: dict) -> tuple[dict, dict]:
    """Translate the Streamlit app's config.json roles into (manager, models)."""
    manager = {
        "policy": "auto",
        # swap_policy 'never' means both models fit — no residency cap
        "max_resident": 0 if app_config.get("swap_policy") == "never" else 1,
        "idle_unload": int(app_config.get("idle_unload_minutes", 0)) * 60,
    }
    models: dict[str, dict] = {}
    for role in ("prompter", "coder"):
        model = app_config.get(f"{role}_model", "")
        backend = app_config.get(f"{role}_backend", "lmstudio")
        if not model:
            continue
        models[role] = {
            "backend": backend,
            "base_url": app_config.get(f"{role}_base_url")
            or BACKEND_DEFAULTS.get(backend, ""),
            "model": model,
        }
    return manager, models


def _template() -> tuple[dict, dict]:
    """Fallback template pointing at the stock local servers."""
    manager = {"policy": "auto", "max_resident": 1, "idle_unload": 0}
    models = {
        "lmstudio-model": {
            "backend": "lmstudio",
            "base_url": BACKEND_DEFAULTS["lmstudio"],
            "model": "REPLACE-WITH-A-MODEL-ID",
        },
        "ollama-model": {
            "backend": "ollama",
            "base_url": BACKEND_DEFAULTS["ollama"],
            "model": "REPLACE-WITH-A-MODEL-ID",
        },
    }
    return manager, models


def ensure_config(path: Path | None = None,
                  app_config_path: Path | None = None) -> Path:
    """Create endpoints.toml if missing (seeded from the app's config.json in
    the working directory when available). Returns the path either way."""
    path = Path(path) if path else default_config_path()
    if path.exists():
        return path
    app_config_path = Path(app_config_path) if app_config_path else Path("config.json")
    manager, models = _template()
    if app_config_path.exists():
        try:
            app_config = json.loads(app_config_path.read_text(encoding="utf-8"))
            seeded_manager, seeded_models = seed_from_app_config(app_config)
            if seeded_models:
                manager, models = seeded_manager, seeded_models
        except (json.JSONDecodeError, OSError):
            pass  # unreadable app config — fall back to the template
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_toml(manager, models), encoding="utf-8")
    return path


def load_endpoints(path: Path | None = None) -> dict:
    """Parse endpoints.toml. Returns {'manager': {...}, 'models': {...}};
    missing sections come back empty."""
    path = Path(path) if path else default_config_path()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        "manager": data.get("manager", {}),
        "models": data.get("models", {}),
    }


def build_manager(path: Path | None = None) -> ModelManager:
    """Construct a fully-registered ModelManager from endpoints.toml."""
    config = load_endpoints(ensure_config(path))
    settings = config["manager"]
    max_resident = settings.get("max_resident", 1)
    manager = ModelManager(
        policy=settings.get("policy", "auto"),
        # 0 in the file means "uncapped" (TOML has no null)
        max_resident=None if not max_resident else int(max_resident),
        vram_budget=settings.get("vram_budget"),
        idle_unload=float(settings.get("idle_unload", 0)),
    )
    for name, fields in config["models"].items():
        endpoint = Endpoint(
            backend=fields.get("backend", "lmstudio"),
            model=fields.get("model", ""),
            base_url=fields.get("base_url", ""),
            api_key=fields.get("api_key", ""),
            vram_hint=fields.get("vram_hint"),
        )
        manager.register(
            name,
            endpoint,
            priority=int(fields.get("priority", 0)),
            idle_unload=(
                float(fields["idle_unload"]) if "idle_unload" in fields else None
            ),
            pinned=bool(fields.get("pinned", False)),
        )
    return manager
