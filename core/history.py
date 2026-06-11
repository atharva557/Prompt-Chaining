"""
PromptChain — Run History

Persists completed runs (task → prompt → code) to history.json so they
survive restarts and can be reopened from the sidebar. Each browser tab
gets its own Streamlit session; the history file is shared, which is the
desired behavior for a single-user local app.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

HISTORY_PATH = Path(__file__).parent.parent / "history.json"
MAX_ENTRIES = 50


def load_history() -> list[dict]:
    """Load history entries, newest first. Returns [] on any problem."""
    if not HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(entries: list[dict]) -> None:
    # Shared across tabs/sessions; concurrent saves are last-writer-wins.
    # Acceptable for a single-user local app (see module docstring).
    HISTORY_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_entry(task: str, prompt: str, code: str, prompter_model: str, coder_model: str) -> dict:
    """Prepend a new run to the history and return the created entry."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "task": task,
        "prompt": prompt,
        "code": code,
        "prompter_model": prompter_model,
        "coder_model": coder_model,
    }
    entries = load_history()
    entries.insert(0, entry)
    _save_history(entries[:MAX_ENTRIES])
    return entry


def get_entry(entry_id: str) -> dict | None:
    """Return the entry with the given id, or None."""
    for entry in load_history():
        if entry["id"] == entry_id:
            return entry
    return None


def delete_entry(entry_id: str) -> None:
    """Remove a single entry from the history."""
    entries = [e for e in load_history() if e["id"] != entry_id]
    _save_history(entries)


def clear_history() -> None:
    """Remove all history entries."""
    _save_history([])
