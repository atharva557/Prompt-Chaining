"""Lifecycle HTTP-shape tests, pinned to responses observed against real
servers (LM Studio 0.4.x /api/v0 + /api/v1, Ollama /api/ps):

- LM Studio names loaded *instances* "key", "key:2", ... — unload must fan
  out over instances, load must be idempotent (a second native load spawns a
  duplicate instance).
- The native load endpoint takes {"model": ...}; unload takes {"instance_id": ...}.
- JIT load/unload fallbacks must send a real token ("ping"), not "" — empty
  content breaks some chat templates (Gemma).
"""

import unittest
from unittest import mock

import promptchain.lifecycle as lifecycle

BASE = "http://localhost:1234"

V0_PAYLOAD = {
    "data": [
        {"id": "qwen/qwen2.5-coder-14b", "state": "loaded",
         "max_context_length": 32768, "loaded_context_length": 11346},
        {"id": "gpt-oss-20b", "state": "not-loaded", "max_context_length": 131072},
        {"id": "google/gemma-4-e4b", "state": "loaded", "max_context_length": 32768},
        {"id": "google/gemma-4-e4b:2", "state": "loaded", "max_context_length": 32768},
    ]
}

V1_PAYLOAD = {
    "models": [
        {"key": "gpt-oss-20b", "loaded_instances": [], "max_context_length": 131072},
        {"key": "google/gemma-4-e4b",
         "loaded_instances": [{"instance_id": "google/gemma-4-e4b"}],
         "max_context_length": 32768},
    ]
}

OLLAMA_PS = {
    "models": [
        {"model": "qwen3:8b", "size_vram": 6_000_000_000, "context_length": 40960},
    ]
}


def _response(status=200, payload=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    return resp


class TestLoadedModels(unittest.TestCase):
    def test_lmstudio_v0_states_and_instances(self):
        def fake_get(url, **kw):
            self.assertIn("/api/v0/models", url)
            return _response(200, V0_PAYLOAD)

        with mock.patch("promptchain.lifecycle.requests.get", side_effect=fake_get):
            entries = lifecycle.loaded_models(BASE, "lmstudio")
        models = [(e["model"], e["instance_id"]) for e in entries]
        self.assertIn(("qwen/qwen2.5-coder-14b", "qwen/qwen2.5-coder-14b"), models)
        # ':2' instance maps back to its model key
        self.assertIn(("google/gemma-4-e4b", "google/gemma-4-e4b:2"), models)
        self.assertNotIn("gpt-oss-20b", [m for m, _ in models])
        # loaded_context_length preferred over max
        self.assertEqual(entries[0]["context_length"], 11346)

    def test_lmstudio_v1_fallback(self):
        def fake_get(url, **kw):
            if "/api/v0/models" in url:
                return _response(404)
            return _response(200, V1_PAYLOAD)

        with mock.patch("promptchain.lifecycle.requests.get", side_effect=fake_get):
            entries = lifecycle.loaded_models(BASE, "lmstudio")
        self.assertEqual(
            entries,
            [{"model": "google/gemma-4-e4b", "instance_id": "google/gemma-4-e4b",
              "vram_bytes": None, "context_length": 32768}],
        )

    def test_ollama_ps(self):
        with mock.patch(
            "promptchain.lifecycle.requests.get",
            return_value=_response(200, OLLAMA_PS),
        ):
            entries = lifecycle.loaded_models("http://localhost:11434", "ollama")
        self.assertEqual(entries[0]["model"], "qwen3:8b")
        self.assertEqual(entries[0]["vram_bytes"], 6_000_000_000)

    def test_custom_and_cloud_return_empty(self):
        self.assertEqual(lifecycle.loaded_models(BASE, "custom"), [])
        self.assertEqual(lifecycle.loaded_models(BASE, "openai"), [])


class TestLoadModel(unittest.TestCase):
    def test_lmstudio_native_load_payload(self):
        posts = []

        def fake_post(url, **kw):
            posts.append((url, kw.get("json")))
            return _response(200, {"status": "loaded"})

        with mock.patch("promptchain.lifecycle.requests.get",
                        return_value=_response(200, {"data": []})), \
             mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            ok = lifecycle.load_model(BASE, "google/gemma-4-e4b", "lmstudio")
        self.assertTrue(ok)
        url, payload = posts[0]
        self.assertIn("/api/v1/models/load", url)
        self.assertEqual(payload, {"model": "google/gemma-4-e4b"})

    def test_lmstudio_load_is_idempotent(self):
        with mock.patch("promptchain.lifecycle.requests.get",
                        return_value=_response(200, V0_PAYLOAD)), \
             mock.patch("promptchain.lifecycle.requests.post") as post:
            ok = lifecycle.load_model(BASE, "google/gemma-4-e4b", "lmstudio")
        self.assertTrue(ok)
        post.assert_not_called()  # no duplicate instance spawned

    def test_jit_fallback_sends_real_token(self):
        posts = []

        def fake_post(url, **kw):
            posts.append((url, kw.get("json")))
            if "/api/v1/models/load" in url:
                return _response(404)
            return _response(200)

        with mock.patch("promptchain.lifecycle.requests.get",
                        return_value=_response(200, {"data": []})), \
             mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            ok = lifecycle.load_model(BASE, "some-model", "lmstudio")
        self.assertTrue(ok)
        jit_payload = posts[-1][1]
        self.assertEqual(jit_payload["messages"][0]["content"], "ping")

    def test_ollama_load_forwards_keep_alive(self):
        posts = []

        def fake_post(url, **kw):
            posts.append((url, kw.get("json")))
            return _response(200)

        with mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            lifecycle.load_model(
                "http://localhost:11434", "qwen3:8b", "ollama", keep_alive="10m"
            )
        url, payload = posts[0]
        self.assertIn("/api/generate", url)
        self.assertEqual(payload["keep_alive"], "10m")

    def test_cloud_is_noop(self):
        with mock.patch("promptchain.lifecycle.requests.post") as post:
            self.assertFalse(lifecycle.load_model("https://x", "m", "openai"))
        post.assert_not_called()

    def test_custom_jit_load_sends_auth_header(self):
        """Authenticated OpenAI-compatible servers (vLLM --api-key,
        llama-swap behind a proxy) need the key on the JIT load."""
        posts = []

        def fake_post(url, **kw):
            posts.append(kw)
            return _response(200)

        with mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            ok = lifecycle.load_model(
                "http://localhost:8080", "m", "custom", api_key="sk-auth"
            )
        self.assertTrue(ok)
        self.assertEqual(posts[0]["headers"]["Authorization"], "Bearer sk-auth")

    def test_keyless_jit_load_has_no_auth_header(self):
        posts = []

        def fake_post(url, **kw):
            posts.append(kw)
            return _response(200)

        with mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            lifecycle.load_model("http://localhost:8080", "m", "custom")
        self.assertNotIn("Authorization", posts[0]["headers"])


class TestUnloadModel(unittest.TestCase):
    def test_lmstudio_unloads_every_instance(self):
        posts = []

        def fake_post(url, **kw):
            posts.append(kw.get("json"))
            return _response(200)

        with mock.patch("promptchain.lifecycle.requests.get",
                        return_value=_response(200, V0_PAYLOAD)), \
             mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            ok = lifecycle.unload_model(BASE, "google/gemma-4-e4b", "lmstudio")
        self.assertTrue(ok)
        self.assertEqual(posts, [
            {"instance_id": "google/gemma-4-e4b"},
            {"instance_id": "google/gemma-4-e4b:2"},
        ])

    def test_lmstudio_unload_does_not_touch_other_models(self):
        posts = []

        def fake_post(url, **kw):
            posts.append(kw.get("json"))
            return _response(200)

        with mock.patch("promptchain.lifecycle.requests.get",
                        return_value=_response(200, V0_PAYLOAD)), \
             mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            lifecycle.unload_model(BASE, "qwen/qwen2.5-coder-14b", "lmstudio")
        self.assertEqual(posts, [{"instance_id": "qwen/qwen2.5-coder-14b"}])

    def test_unload_of_not_loaded_model_never_fires_ttl_trick(self):
        """Verified live: the ttl=0 completion LOADS an unloaded model (and
        modern LM Studio ignores ttl=0). With a working listing that says the
        model isn't resident, unload must do nothing at all."""
        with mock.patch("promptchain.lifecycle.requests.get",
                        return_value=_response(200, {"data": []})), \
             mock.patch("promptchain.lifecycle.requests.post") as post:
            ok = lifecycle.unload_model(BASE, "google/gemma-4-e4b", "lmstudio")
        self.assertTrue(ok)  # already not loaded — success, nothing to do
        post.assert_not_called()

    def test_blind_legacy_path_when_no_listing_api(self):
        """Very old LM Studio (no /api/v0 or /api/v1 listing): native unload
        by model key first, TTL trick as the last resort."""
        posts = []

        def fake_post(url, **kw):
            posts.append((url, kw.get("json")))
            return _response(404 if "/api/v1/models/unload" in url else 200)

        with mock.patch("promptchain.lifecycle.requests.get",
                        return_value=_response(404)), \
             mock.patch("promptchain.lifecycle.requests.post", side_effect=fake_post):
            ok = lifecycle.unload_model(BASE, "some-model", "lmstudio")
        self.assertTrue(ok)
        self.assertIn("/api/v1/models/unload", posts[0][0])
        # TTL fallback fired with a real token and ttl=0
        ttl_payload = posts[-1][1]
        self.assertEqual(ttl_payload["ttl"], 0)
        self.assertEqual(ttl_payload["messages"][0]["content"], "ping")


if __name__ == "__main__":
    unittest.main()
