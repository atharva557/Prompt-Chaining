"""Validates presets/presets.json structure and the invariants the app relies on."""

import unittest

from core.config import load_presets


class TestPresetsFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.presets = load_presets()

    def test_top_level_roles(self):
        self.assertIn("prompter", self.presets)
        self.assertIn("coder", self.presets)

    def test_structure_and_nonempty_text(self):
        # role -> category -> name -> non-empty string
        for role in ("prompter", "coder"):
            self.assertTrue(self.presets[role], f"{role} has no categories")
            for category, entries in self.presets[role].items():
                self.assertIsInstance(entries, dict, f"{role}/{category} is not a dict")
                self.assertTrue(entries, f"{role}/{category} is empty")
                for name, text in entries.items():
                    self.assertIsInstance(text, str, f"{role}/{category}/{name}")
                    self.assertGreater(
                        len(text.strip()), 50,
                        f"{role}/{category}/{name} is suspiciously short",
                    )

    def test_minimum_preset_count(self):
        total = sum(
            len(entries)
            for role in ("prompter", "coder")
            for entries in self.presets[role].values()
        )
        self.assertGreaterEqual(total, 13, "preset library shrank below spec minimum")

    def test_prompter_presets_demand_prompt_only_output(self):
        # Small local models drift without an explicit output constraint.
        for category, entries in self.presets["prompter"].items():
            for name, text in entries.items():
                self.assertIn(
                    "output only", text.lower(),
                    f"prompter/{category}/{name} lacks an 'Output ONLY ...' rule",
                )

    def test_coder_presets_demand_fenced_block(self):
        # extract_code() in ui/code_output.py relies on a fenced code block.
        for category, entries in self.presets["coder"].items():
            for name, text in entries.items():
                self.assertIn(
                    "fenced code block", text.lower(),
                    f"coder/{category}/{name} lacks the fenced-code-block rule",
                )


if __name__ == "__main__":
    unittest.main()
