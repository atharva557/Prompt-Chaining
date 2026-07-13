"""endpoints.toml handling: seeding from the app's config.json, the fallback
template, round-tripping, and ModelManager construction."""

import json
import unittest
import tempfile
from pathlib import Path

from promptchain.endpoints_file import (
    build_manager,
    ensure_config,
    load_endpoints,
)


class EndpointsFileTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.toml_path = self.dir / "endpoints.toml"
        self.app_config = self.dir / "config.json"


class TestSeeding(EndpointsFileTestCase):
    def test_seeded_from_app_config(self):
        self.app_config.write_text(json.dumps({
            "prompter_backend": "lmstudio",
            "prompter_base_url": "http://localhost:1234",
            "prompter_model": "gemma-4-4b",
            "coder_backend": "ollama",
            "coder_base_url": "http://localhost:11434",
            "coder_model": "qwen3-coder:30b",
            "idle_unload_minutes": 5,
            "swap_policy": "auto",
        }), encoding="utf-8")
        path = ensure_config(self.toml_path, app_config_path=self.app_config)
        config = load_endpoints(path)
        self.assertEqual(config["manager"]["idle_unload"], 300)
        self.assertEqual(config["manager"]["max_resident"], 1)
        self.assertEqual(config["models"]["prompter"]["model"], "gemma-4-4b")
        self.assertEqual(config["models"]["coder"]["backend"], "ollama")

    def test_swap_never_becomes_uncapped(self):
        self.app_config.write_text(json.dumps({
            "prompter_model": "a", "coder_model": "b",
            "swap_policy": "never", "idle_unload_minutes": 0,
        }), encoding="utf-8")
        ensure_config(self.toml_path, app_config_path=self.app_config)
        manager = build_manager(self.toml_path)
        self.assertIsNone(manager.max_resident)

    def test_template_when_no_app_config(self):
        path = ensure_config(self.toml_path, app_config_path=self.dir / "missing.json")
        config = load_endpoints(path)
        self.assertEqual(len(config["models"]), 2)
        self.assertIn("lmstudio-model", config["models"])

    def test_existing_file_is_never_overwritten(self):
        self.toml_path.write_text("[manager]\npolicy = \"manual\"\n", encoding="utf-8")
        ensure_config(self.toml_path, app_config_path=self.app_config)
        self.assertEqual(load_endpoints(self.toml_path)["manager"]["policy"], "manual")

    def test_no_api_keys_are_written(self):
        self.app_config.write_text(json.dumps({
            "prompter_model": "a", "coder_model": "b",
            "api_keys": {"openai": "sk-secret"},
        }), encoding="utf-8")
        path = ensure_config(self.toml_path, app_config_path=self.app_config)
        self.assertNotIn("sk-secret", path.read_text(encoding="utf-8"))


class TestBuildManager(EndpointsFileTestCase):
    def test_full_registration(self):
        self.toml_path.write_text(
            "\n".join([
                "[manager]",
                'policy = "manual"',
                "max_resident = 2",
                "idle_unload = 120",
                'vram_budget = "20GiB"',
                "",
                "[models.coder]",
                'backend = "ollama"',
                'base_url = "http://localhost:11434"',
                'model = "qwen3-coder:30b"',
                "priority = 10",
                "pinned = true",
                "idle_unload = 60",
                'vram_hint = "18GiB"',
                "",
                "[models.reviewer]",
                'backend = "anthropic"',
                'model = "claude-sonnet-5"',
                'api_key = "sk-file"',
            ]) + "\n",
            encoding="utf-8",
        )
        manager = build_manager(self.toml_path)
        self.assertEqual(manager.policy, "manual")
        self.assertEqual(manager.max_resident, 2)
        self.assertEqual(manager.vram_budget, 20 * 2**30)
        self.assertEqual(manager.idle_unload, 120.0)
        stats = manager.stats()
        self.assertEqual(stats["coder"]["priority"], 10)
        self.assertTrue(stats["coder"]["pinned"])
        self.assertEqual(stats["coder"]["vram_bytes"], 18 * 2**30)
        self.assertEqual(manager.endpoint("reviewer").api_key, "sk-file")
        self.assertEqual(
            manager.endpoint("reviewer").base_url, "https://api.anthropic.com"
        )


if __name__ == "__main__":
    unittest.main()
