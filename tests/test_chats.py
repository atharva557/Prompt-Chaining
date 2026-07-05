"""Tests for chat persistence (uses a temp chats path)."""

import tempfile
import unittest
from pathlib import Path

import core.chats as chats_mod


class ChatsTestCase(unittest.TestCase):
    """Redirects CHATS_PATH to a temp file so tests never touch real chats."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = chats_mod.CHATS_PATH
        chats_mod.CHATS_PATH = Path(self._tmpdir.name) / "chats.json"

    def tearDown(self):
        chats_mod.CHATS_PATH = self._orig_path
        self._tmpdir.cleanup()


class TestChats(ChatsTestCase):
    def test_empty_when_missing(self):
        self.assertEqual(chats_mod.load_chat_messages("prompter"), [])

    def test_round_trip(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        chats_mod.save_chat_messages("prompter", msgs)
        self.assertEqual(chats_mod.load_chat_messages("prompter"), msgs)

    def test_roles_are_independent(self):
        chats_mod.save_chat_messages("prompter", [{"role": "user", "content": "p"}])
        chats_mod.save_chat_messages("coder", [{"role": "user", "content": "c"}])
        self.assertEqual(chats_mod.load_chat_messages("prompter")[0]["content"], "p")
        self.assertEqual(chats_mod.load_chat_messages("coder")[0]["content"], "c")

    def test_save_empty_clears(self):
        chats_mod.save_chat_messages("coder", [{"role": "user", "content": "x"}])
        chats_mod.save_chat_messages("coder", [])
        self.assertEqual(chats_mod.load_chat_messages("coder"), [])

    def test_trimmed_to_max_messages(self):
        msgs = [
            {"role": "user", "content": str(i)}
            for i in range(chats_mod.MAX_MESSAGES + 10)
        ]
        chats_mod.save_chat_messages("prompter", msgs)
        loaded = chats_mod.load_chat_messages("prompter")
        self.assertEqual(len(loaded), chats_mod.MAX_MESSAGES)
        # newest messages survive the trim
        self.assertEqual(loaded[-1]["content"], msgs[-1]["content"])

    def test_corrupt_file_returns_empty(self):
        chats_mod.CHATS_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(chats_mod.load_chat_messages("prompter"), [])


if __name__ == "__main__":
    unittest.main()
