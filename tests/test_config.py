"""Tests for config load/save and preset merging (uses a temp config path)."""

import tempfile
import unittest
from pathlib import Path

import core.config as config_mod


class ConfigTestCase(unittest.TestCase):
    """Redirects CONFIG_PATH to a temp file so tests never touch the real config."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = config_mod.CONFIG_PATH
        config_mod.CONFIG_PATH = Path(self._tmpdir.name) / "config.json"

    def tearDown(self):
        config_mod.CONFIG_PATH = self._orig_path
        self._tmpdir.cleanup()


class TestDefaults(ConfigTestCase):
    def test_default_config_has_required_keys(self):
        defaults = config_mod.get_default_config()
        for key in (
            "backend", "base_url", "prompter_model", "coder_model",
            "output_folder", "prompter_temperature", "coder_temperature",
            "prompter_max_tokens", "coder_max_tokens", "custom_presets",
        ):
            self.assertIn(key, defaults)

    def test_load_returns_defaults_when_missing(self):
        self.assertEqual(config_mod.load_config(), config_mod.get_default_config())

    def test_config_exists_false_when_missing(self):
        self.assertFalse(config_mod.config_exists())


class TestSaveLoad(ConfigTestCase):
    def test_round_trip(self):
        cfg = config_mod.get_default_config()
        cfg["prompter_model"] = "phi-4-mini"
        cfg["coder_model"] = "qwen2.5-coder"
        config_mod.save_config(cfg)
        self.assertEqual(config_mod.load_config(), cfg)
        self.assertTrue(config_mod.config_exists())

    def test_config_exists_false_when_models_empty(self):
        config_mod.save_config(config_mod.get_default_config())
        self.assertFalse(config_mod.config_exists())

    def test_load_merges_missing_keys_with_defaults(self):
        config_mod.CONFIG_PATH.write_text('{"base_url": "http://x:1"}', encoding="utf-8")
        cfg = config_mod.load_config()
        self.assertEqual(cfg["base_url"], "http://x:1")
        self.assertEqual(cfg["coder_temperature"], 0.1)  # default filled in

    def test_load_survives_corrupt_json(self):
        config_mod.CONFIG_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(config_mod.load_config(), config_mod.get_default_config())


class TestCustomPresets(ConfigTestCase):
    def test_save_and_merge_custom_preset(self):
        cfg = config_mod.get_default_config()
        cfg = config_mod.save_custom_preset(cfg, "My Preset", "prompter", "be terse")
        merged = config_mod.get_merged_presets(cfg)
        self.assertEqual(merged["prompter"]["Custom"]["My Preset"], "be terse")

    def test_delete_custom_preset(self):
        cfg = config_mod.get_default_config()
        cfg = config_mod.save_custom_preset(cfg, "Temp", "coder", "x")
        cfg = config_mod.delete_custom_preset(cfg, "Temp")
        self.assertNotIn("Temp", cfg["custom_presets"])


if __name__ == "__main__":
    unittest.main()
