"""
PromptChain — Chat Persistence

Persists the two single-model chats (Prompter / Coder) to chats.json so a
conversation survives app restarts, mirroring how history.json persists
pipeline runs. Shared across tabs/sessions; concurrent saves are
last-writer-wins, which is acceptable for a single-user local app.
"""

import json
from pathlib import Path

CHATS_PATH = Path(__file__).parent.parent / "chats.json"
# Keep persisted conversations from growing without bound
MAX_MESSAGES = 200


def _load_all() -> dict:
    if not CHATS_PATH.exists():
        return {}
    try:
        data = json.loads(CHATS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_chat_messages(role: str) -> list[dict]:
    """Persisted messages for 'prompter' or 'coder'. [] on any problem."""
    msgs = _load_all().get(role, [])
    return msgs if isinstance(msgs, list) else []


def save_chat_messages(role: str, messages: list[dict]) -> None:
    """Persist one role's conversation (trimmed to the newest MAX_MESSAGES)."""
    data = _load_all()
    data[role] = messages[-MAX_MESSAGES:]
    CHATS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
