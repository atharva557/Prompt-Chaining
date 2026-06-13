"""Smoke tests for app.py via Streamlit's AppTest (no LLM server needed).

Network calls (connection badge) fail fast against a closed local port and
are handled by the app, so these tests only verify that every page renders
without exceptions and that navigation moves between pages correctly.
"""

import json
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

import core.config as config_mod
import core.history as history_mod

APP_PATH = str(Path(__file__).parent.parent / "app.py")


class AppSmokeTestCase(unittest.TestCase):
    """Runs app.py against temp config/history so tests never touch real files."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self._orig_config_path = config_mod.CONFIG_PATH
        self._orig_history_path = history_mod.HISTORY_PATH
        config_mod.CONFIG_PATH = tmp / "config.json"
        history_mod.HISTORY_PATH = tmp / "history.json"
        cfg = config_mod.get_default_config()
        cfg["prompter_model"] = "test-prompter"
        cfg["coder_model"] = "test-coder"
        config_mod.save_config(cfg)

    def tearDown(self):
        config_mod.CONFIG_PATH = self._orig_config_path
        history_mod.HISTORY_PATH = self._orig_history_path
        self._tmpdir.cleanup()

    def _run_app(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()
        return at


class TestLanding(AppSmokeTestCase):
    def test_landing_renders_without_exception(self):
        at = self._run_app()
        self.assertFalse(at.exception)
        keys = [b.key for b in at.button]
        self.assertIn("landing_pipeline_btn", keys)
        self.assertIn("landing_chat_prompter_btn", keys)
        self.assertIn("landing_chat_coder_btn", keys)

    def test_landing_to_pipeline(self):
        at = self._run_app()
        at.button(key="landing_pipeline_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["page"], "pipeline")
        self.assertIn("generate_prompt_btn", [b.key for b in at.button])


class TestNavigation(AppSmokeTestCase):
    def test_sidebar_nav_to_prompter_chat(self):
        at = self._run_app()
        at.button(key="nav_chat_prompter_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["page"], "chat_prompter")

    def test_sidebar_nav_to_coder_chat_and_home(self):
        at = self._run_app()
        at.button(key="nav_chat_coder_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["page"], "chat_coder")
        at.button(key="nav_home_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["page"], "landing")

    def test_new_task_opens_pipeline(self):
        at = self._run_app()
        at.button(key="new_task_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["page"], "pipeline")
        self.assertEqual(at.session_state["current_step"], 0)


class TestLegacyConfigBoots(AppSmokeTestCase):
    """A pre-cloud config file must migrate and boot the app unchanged."""

    def test_legacy_config_renders_landing(self):
        # Overwrite the temp config with the old single-backend schema
        config_mod.CONFIG_PATH.write_text(
            json.dumps({
                "backend": "lmstudio",
                "base_url": "http://localhost:1234",
                "prompter_model": "test-prompter",
                "coder_model": "test-coder",
            }),
            encoding="utf-8",
        )
        at = self._run_app()
        self.assertFalse(at.exception)
        # Migrated config exposes per-role endpoints
        cfg = at.session_state["config"]
        self.assertEqual(cfg["prompter_backend"], "lmstudio")
        self.assertEqual(cfg["coder_backend"], "lmstudio")
        self.assertIn("landing_pipeline_btn", [b.key for b in at.button])


class TestHybridConfigBoots(AppSmokeTestCase):
    """Local Prompter + cloud Coder must render landing + the per-role sidebar
    badges without a network call (no key → connection check short-circuits)."""

    def test_landing_and_sidebar_render_for_hybrid(self):
        config_mod.CONFIG_PATH.write_text(
            json.dumps({
                "prompter_backend": "lmstudio",
                "prompter_base_url": "http://localhost:1234",
                "coder_backend": "anthropic",
                "coder_base_url": "https://api.anthropic.com",
                "prompter_model": "test-prompter",
                "coder_model": "claude-opus-4-8",
                "api_keys": {"openai": "", "anthropic": "", "gemini": ""},
            }),
            encoding="utf-8",
        )
        at = self._run_app()
        self.assertFalse(at.exception)
        self.assertIn("landing_pipeline_btn", [b.key for b in at.button])


class TestSettingsPage(AppSmokeTestCase):
    def test_settings_renders_for_cloud_backend(self):
        # A coder on a cloud backend should render the API-keys section + save
        config_mod.CONFIG_PATH.write_text(
            json.dumps({
                "prompter_backend": "lmstudio",
                "prompter_base_url": "http://localhost:1234",
                "coder_backend": "anthropic",
                "coder_base_url": "https://api.anthropic.com",
                "prompter_model": "test-prompter",
                "coder_model": "claude-opus-4-8",
                "api_keys": {"openai": "", "anthropic": "", "gemini": ""},
            }),
            encoding="utf-8",
        )
        at = self._run_app()
        at.session_state["show_settings"] = True
        at.run()
        self.assertFalse(at.exception)
        self.assertIn("save_settings_btn", [b.key for b in at.button])


class TestPresetsPage(AppSmokeTestCase):
    def test_presets_page_renders_and_lists_presets(self):
        at = self._run_app()
        at.button(key="nav_presets_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["page"], "presets")
        keys = [b.key for b in at.button]
        self.assertIn("presets_back_btn", keys)
        # The "New custom preset" create button exists for at least one role
        self.assertIn("create_preset_prompter", keys)


class TestPipelinePages(AppSmokeTestCase):
    """Render the review and output steps by seeding session state."""

    def test_review_page_renders_with_diff(self):
        at = self._run_app()
        at.session_state["page"] = "pipeline"
        at.session_state["current_step"] = 1
        at.session_state["task_description"] = "make a snake game"
        at.session_state["generated_prompt"] = "## Goal\nBuild a snake game"
        at.run()
        self.assertFalse(at.exception)
        self.assertIn("confirm_prompt_btn", [b.key for b in at.button])

    def test_output_page_renders_with_refine_box(self):
        at = self._run_app()
        at.session_state["page"] = "pipeline"
        at.session_state["current_step"] = 3
        at.session_state["task_description"] = "make a snake game in python"
        at.session_state["generated_prompt"] = "prompt"
        at.session_state["generated_code"] = "```python\nprint('hi')\n```"
        at.run()
        self.assertFalse(at.exception)
        keys = [b.key for b in at.button]
        self.assertIn("refine_code_btn", keys)
        self.assertIn("regenerate_code_btn", keys)


if __name__ == "__main__":
    unittest.main()
