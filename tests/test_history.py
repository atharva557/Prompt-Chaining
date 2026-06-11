"""Tests for run history persistence (uses a temp history path)."""

import tempfile
import unittest
from pathlib import Path

import core.history as history_mod


class HistoryTestCase(unittest.TestCase):
    """Redirects HISTORY_PATH to a temp file so tests never touch real history."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = history_mod.HISTORY_PATH
        history_mod.HISTORY_PATH = Path(self._tmpdir.name) / "history.json"

    def tearDown(self):
        history_mod.HISTORY_PATH = self._orig_path
        self._tmpdir.cleanup()

    def _add(self, task="task"):
        return history_mod.add_entry(
            task=task, prompt="p", code="c",
            prompter_model="m1", coder_model="m2",
        )


class TestHistory(HistoryTestCase):
    def test_empty_when_missing(self):
        self.assertEqual(history_mod.load_history(), [])

    def test_add_and_load_newest_first(self):
        self._add("first")
        self._add("second")
        entries = history_mod.load_history()
        self.assertEqual([e["task"] for e in entries], ["second", "first"])

    def test_entry_fields(self):
        entry = self._add("my task")
        self.assertEqual(entry["task"], "my task")
        for key in ("id", "timestamp", "prompt", "code", "prompter_model", "coder_model"):
            self.assertIn(key, entry)

    def test_capped_at_max_entries(self):
        for i in range(history_mod.MAX_ENTRIES + 5):
            self._add(f"task {i}")
        self.assertEqual(len(history_mod.load_history()), history_mod.MAX_ENTRIES)

    def test_get_and_delete_entry(self):
        entry = self._add("findme")
        self.assertIsNotNone(history_mod.get_entry(entry["id"]))
        history_mod.delete_entry(entry["id"])
        self.assertIsNone(history_mod.get_entry(entry["id"]))

    def test_clear(self):
        self._add()
        history_mod.clear_history()
        self.assertEqual(history_mod.load_history(), [])

    def test_corrupt_file_returns_empty(self):
        history_mod.HISTORY_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(history_mod.load_history(), [])


if __name__ == "__main__":
    unittest.main()
