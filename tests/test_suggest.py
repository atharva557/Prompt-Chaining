"""Tests for the keyword → preset-pair suggestion engine (core/suggest.py)."""

import unittest

from core.config import load_presets
from core.suggest import suggest_presets, SUGGESTION_RULES


class TestRuleIntegrity(unittest.TestCase):
    """Every rule must point at presets that actually ship — a renamed preset
    in presets.json would otherwise silently break the Apply button."""

    def test_every_rule_points_at_a_shipped_preset(self):
        presets = load_presets()
        for label, _keywords, (p_cat, p_name), (c_cat, c_name) in SUGGESTION_RULES:
            self.assertIn(
                p_name, presets["prompter"].get(p_cat, {}),
                f"rule '{label}': prompter preset {p_cat}/{p_name} missing",
            )
            self.assertIn(
                c_name, presets["coder"].get(c_cat, {}),
                f"rule '{label}': coder preset {c_cat}/{c_name} missing",
            )


class TestSuggestPresets(unittest.TestCase):
    def _pair(self, task):
        suggestion = suggest_presets(task)
        self.assertIsNotNone(suggestion, f"expected a suggestion for: {task}")
        return suggestion["prompter"][1], suggestion["coder"][1]

    def test_game_task(self):
        p, c = self._pair("a snake game with high scores")
        self.assertEqual(p, "Browser Game Designer")
        self.assertEqual(c, "Browser Game Developer")

    def test_bug_fix_task(self):
        p, c = self._pair("fix the crash in my parser when the input is empty")
        self.assertEqual(p, "Bug Fix Brief")
        self.assertEqual(c, "Debugger & Refactorer")

    def test_ml_task(self):
        _p, c = self._pair("train a classifier on the iris dataset")
        self.assertEqual(c, "ML Engineer")

    def test_rust_task(self):
        p, c = self._pair("a fast grep clone in rust")
        self.assertEqual(p, "Systems Program Spec")
        self.assertEqual(c, "Rust")

    def test_framework_beats_language(self):
        # "react ... typescript" should suggest the React pair (which handles
        # TypeScript via tsx), not the generic TypeScript coder
        _p, c = self._pair("a react todo app in typescript")
        self.assertEqual(c, "React")

    def test_language_beats_generic_cli(self):
        # "cli tool in rust" must not fall through to the Python-default CLI pair
        _p, c = self._pair("a cli tool in rust that renames files")
        self.assertEqual(c, "Rust")

    def test_cli_task(self):
        _p, c = self._pair("a cli tool that renames files in bulk")
        self.assertEqual(c, "CLI Tool Developer")

    def test_scraper_task(self):
        p, _c = self._pair("scrape product prices from a shop page")
        self.assertEqual(p, "Automation & Scraping")

    def test_sql_task(self):
        _p, c = self._pair("sql queries to find the top customers per region")
        self.assertEqual(c, "SQL")

    def test_whole_word_matching(self):
        # "go" must not fire inside "logo"; html should win here
        suggestion = suggest_presets("a logo gallery page in html")
        self.assertEqual(suggestion["coder"][1], "Single-File Web App")

    def test_no_match_returns_none(self):
        self.assertIsNone(suggest_presets("please make something nice"))
        self.assertIsNone(suggest_presets(""))
        self.assertIsNone(suggest_presets("   "))
        self.assertIsNone(suggest_presets(None))


if __name__ == "__main__":
    unittest.main()
