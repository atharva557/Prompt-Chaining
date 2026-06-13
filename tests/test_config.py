"""Tests for config load/save and preset merging (uses a temp config path)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            "prompter_backend", "prompter_base_url",
            "coder_backend", "coder_base_url",
            "prompter_model", "coder_model", "api_keys",
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


class TestLegacyMigration(ConfigTestCase):
    def test_legacy_single_backend_migrates_to_per_role(self):
        # A pre-cloud config: one global backend + base_url, no per-role keys
        config_mod.CONFIG_PATH.write_text(
            json.dumps({
                "backend": "ollama",
                "base_url": "http://localhost:11434",
                "prompter_model": "phi", "coder_model": "qwen",
            }),
            encoding="utf-8",
        )
        cfg = config_mod.load_config()
        self.assertEqual(cfg["prompter_backend"], "ollama")
        self.assertEqual(cfg["coder_backend"], "ollama")
        self.assertEqual(cfg["prompter_base_url"], "http://localhost:11434")
        self.assertEqual(cfg["coder_base_url"], "http://localhost:11434")
        self.assertIn("api_keys", cfg)

    def test_legacy_config_still_counts_as_existing(self):
        config_mod.CONFIG_PATH.write_text(
            json.dumps({
                "backend": "lmstudio",
                "base_url": "http://localhost:1234",
                "prompter_model": "phi", "coder_model": "qwen",
            }),
            encoding="utf-8",
        )
        self.assertTrue(config_mod.config_exists())


class TestRoleEndpoint(ConfigTestCase):
    def test_resolves_per_role_endpoint(self):
        cfg = config_mod.get_default_config()
        cfg["coder_backend"] = "anthropic"
        cfg["coder_base_url"] = "https://api.anthropic.com"
        cfg["coder_model"] = "claude-opus-4-8"
        ep = config_mod.get_role_endpoint(cfg, "coder")
        self.assertEqual(ep["backend"], "anthropic")
        self.assertEqual(ep["base_url"], "https://api.anthropic.com")
        self.assertEqual(ep["model"], "claude-opus-4-8")

    def test_base_url_falls_back_to_backend_default(self):
        cfg = config_mod.get_default_config()
        cfg["prompter_backend"] = "openai"
        cfg["prompter_base_url"] = ""  # not set
        ep = config_mod.get_role_endpoint(cfg, "prompter")
        self.assertEqual(ep["base_url"], "https://api.openai.com")

    def test_env_var_takes_precedence_over_config_key(self):
        cfg = config_mod.get_default_config()
        cfg["coder_backend"] = "openai"
        cfg["api_keys"]["openai"] = "from-config"
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "from-env"}):
            ep = config_mod.get_role_endpoint(cfg, "coder")
            self.assertEqual(ep["api_key"], "from-env")

    def test_config_key_used_when_no_env_var(self):
        cfg = config_mod.get_default_config()
        cfg["coder_backend"] = "openai"
        cfg["api_keys"]["openai"] = "from-config"
        with mock.patch.dict(os.environ, {}, clear=True):
            ep = config_mod.get_role_endpoint(cfg, "coder")
            self.assertEqual(ep["api_key"], "from-config")

    def test_local_backend_has_no_key(self):
        cfg = config_mod.get_default_config()
        ep = config_mod.get_role_endpoint(cfg, "prompter")
        self.assertEqual(ep["api_key"], "")


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
