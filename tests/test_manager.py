"""ModelManager unit tests — the eviction matrix, policies, pinning, groups,
idle timers, residency reconciliation, and stats.

No live servers: promptchain.lifecycle's HTTP functions are patched at the
module level (manager.py looks them up through the module object at call
time, so patching promptchain.lifecycle.* is seen by the manager).
"""

import threading
import time
import unittest
from unittest import mock

from promptchain import Endpoint, ModelManager
from promptchain.errors import ModelNotRegistered, ModelNotResident
from promptchain.streaming import StreamingResponse


def _patch_lifecycle(load=True, unload=True, loaded=None):
    """Patch the three lifecycle HTTP calls; returns the three mocks."""
    load_p = mock.patch("promptchain.lifecycle.load_model", return_value=load)
    unload_p = mock.patch("promptchain.lifecycle.unload_model", return_value=unload)
    loaded_p = mock.patch(
        "promptchain.lifecycle.loaded_models", return_value=loaded or []
    )
    return load_p, unload_p, loaded_p


class ManagerTestCase(unittest.TestCase):
    """Base: every test runs with lifecycle HTTP mocked out."""

    def setUp(self):
        load_p, unload_p, loaded_p = _patch_lifecycle()
        self.load_mock = load_p.start()
        self.unload_mock = unload_p.start()
        self.loaded_mock = loaded_p.start()
        self.addCleanup(mock.patch.stopall)


class TestRegistry(ManagerTestCase):
    def test_register_and_names(self):
        mgr = ModelManager()
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("ollama", "model-b"))
        self.assertEqual(sorted(mgr.names()), ["a", "b"])

    def test_duplicate_register_raises(self):
        mgr = ModelManager()
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        with self.assertRaises(ValueError):
            mgr.register("a", Endpoint("ollama", "model-a2"))

    def test_unknown_name_raises(self):
        mgr = ModelManager()
        with self.assertRaises(ModelNotRegistered):
            mgr.load("ghost")

    def test_unregister_removes_from_groups(self):
        mgr = ModelManager()
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        mgr.group("g", ["a", "b"])
        mgr.unregister("a")
        self.assertEqual(mgr.names(), ["b"])
        # activate must not trip over the removed member
        mgr.activate("g")
        self.assertEqual(mgr.resident(), ["b"])


class TestAutoPolicy(ManagerTestCase):
    def test_use_loads_nonresident_model(self):
        mgr = ModelManager(policy="auto")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        with mgr.use("a"):
            pass
        self.load_mock.assert_called_once()
        self.assertEqual(mgr.resident(), ["a"])

    def test_lru_eviction_under_max_resident(self):
        mgr = ModelManager(policy="auto", max_resident=1)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        evicted = []
        mgr.on_evict(lambda name, reason: evicted.append((name, reason)))
        with mgr.use("a"):
            pass
        with mgr.use("b"):
            pass
        self.assertEqual(evicted, [("a", "evicted")])
        self.assertEqual(mgr.resident(), ["b"])

    def test_lowest_priority_evicted_first(self):
        mgr = ModelManager(policy="auto", max_resident=2)
        mgr.register("old_important", Endpoint("lmstudio", "m1"), priority=10)
        mgr.register("fresh_cheap", Endpoint("lmstudio", "m2"), priority=1)
        mgr.register("incoming", Endpoint("lmstudio", "m3"))
        evicted = []
        mgr.on_evict(lambda name, reason: evicted.append(name))
        with mgr.use("old_important"):
            pass
        with mgr.use("fresh_cheap"):
            pass  # more recently used, but lower priority
        with mgr.use("incoming"):
            pass
        self.assertEqual(evicted, ["fresh_cheap"])

    def test_pinned_model_survives_eviction(self):
        mgr = ModelManager(policy="auto", max_resident=1)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        with mgr.use("a"):
            pass
        mgr.pin("a")
        with mgr.use("b"):
            pass  # nothing evictable — proceeds best-effort
        self.assertEqual(sorted(mgr.resident()), ["a", "b"])
        self.unload_mock.assert_not_called()

    def test_cloud_and_custom_never_counted_or_evicted(self):
        mgr = ModelManager(policy="auto", max_resident=1)
        mgr.register("local", Endpoint("lmstudio", "model-a"))
        mgr.register("cloud", Endpoint("anthropic", "claude-sonnet-5", api_key="k"))
        mgr.register("opaque", Endpoint("custom", "some-model"))
        with mgr.use("local"):
            pass
        with mock.patch("promptchain.manager.stream") as fake_stream:
            fake_stream.return_value = StreamingResponse(iter([]), {}, {}, [])
            with mgr.use("cloud"):
                pass
            with mgr.use("opaque"):
                pass
        # the local model was never evicted by cloud/custom usage
        self.assertEqual(mgr.resident(), ["local"])
        self.unload_mock.assert_not_called()
        # and load() is a no-op for cloud
        self.assertFalse(mgr.load("cloud"))

    def test_vram_budget_eviction(self):
        mgr = ModelManager(policy="auto", max_resident=None, vram_budget="20GiB")
        mgr.register("big", Endpoint("lmstudio", "m1", vram_hint="18GiB"))
        mgr.register("mid", Endpoint("lmstudio", "m2", vram_hint="10GiB"))
        mgr.register("tiny", Endpoint("lmstudio", "m3", vram_hint="1GiB"))
        evicted = []
        mgr.on_evict(lambda name, reason: evicted.append(name))
        with mgr.use("big"):
            pass
        with mgr.use("tiny"):
            pass  # 18 + 1 fits in 20 — no eviction
        self.assertEqual(evicted, [])
        with mgr.use("mid"):
            pass  # 18 + 1 + 10 > 20 — evict LRU until it fits
        self.assertIn("big", evicted)
        self.assertNotIn("mid", evicted)

    def test_unknown_sizes_do_not_trigger_budget(self):
        mgr = ModelManager(policy="auto", max_resident=None, vram_budget="1GiB")
        mgr.register("a", Endpoint("lmstudio", "m1"))  # size unknown → counts 0
        mgr.register("b", Endpoint("lmstudio", "m2"))
        with mgr.use("a"):
            pass
        with mgr.use("b"):
            pass
        self.unload_mock.assert_not_called()

    def test_busy_victim_is_skipped(self):
        mgr = ModelManager(policy="auto", max_resident=1)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        holding, release = threading.Event(), threading.Event()

        def hold_a():
            with mgr.use("a"):
                holding.set()
                release.wait(timeout=5)

        worker = threading.Thread(target=hold_a, daemon=True)
        worker.start()
        self.assertTrue(holding.wait(timeout=5))
        # 'a' is mid-use on another thread: eviction must skip it, not block
        self.assertTrue(mgr.load("b"))
        self.unload_mock.assert_not_called()
        release.set()
        worker.join(timeout=5)
        self.assertEqual(sorted(mgr.resident()), ["a", "b"])


class TestManualPolicy(ManagerTestCase):
    def test_use_nonresident_raises(self):
        mgr = ModelManager(policy="manual")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        with self.assertRaises(ModelNotResident):
            with mgr.use("a"):
                pass

    def test_explicit_load_then_use(self):
        mgr = ModelManager(policy="manual")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        self.assertTrue(mgr.load("a"))
        with mgr.use("a"):
            pass
        self.assertEqual(mgr.resident(), ["a"])

    def test_load_never_evicts_implicitly(self):
        mgr = ModelManager(policy="manual", max_resident=1)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        mgr.load("a")
        mgr.load("b")  # manual: max_resident is not enforced implicitly
        self.assertEqual(sorted(mgr.resident()), ["a", "b"])
        self.unload_mock.assert_not_called()

    def test_swap_is_the_explicit_path(self):
        mgr = ModelManager(policy="manual")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        mgr.load("a")
        self.assertTrue(mgr.swap("a", "b"))
        self.assertEqual(mgr.resident(), ["b"])
        self.unload_mock.assert_called_once()


class TestGroups(ManagerTestCase):
    def test_activate_swaps_working_set(self):
        mgr = ModelManager(policy="auto", max_resident=None)
        for name in ("drafter", "critic", "fixer"):
            mgr.register(name, Endpoint("lmstudio", name))
        mgr.register("pinned_embed", Endpoint("ollama", "embed"), pinned=True)
        mgr.group("review", ["critic", "fixer"])
        with mgr.use("drafter"):
            pass
        with mgr.use("pinned_embed"):
            pass
        results = mgr.activate("review")
        self.assertEqual(results, {"critic": True, "fixer": True})
        # drafter evicted; pinned model survived; members resident
        self.assertEqual(
            sorted(mgr.resident()), ["critic", "fixer", "pinned_embed"]
        )

    def test_unknown_group_raises(self):
        mgr = ModelManager()
        with self.assertRaises(KeyError):
            mgr.activate("nope")


class TestIdleTimers(ManagerTestCase):
    def test_idle_fire_unloads_and_reports(self):
        mgr = ModelManager(policy="auto", idle_unload=0.05)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        evicted = []
        mgr.on_evict(lambda name, reason: evicted.append((name, reason)))
        with mgr.use("a"):
            pass
        deadline = time.monotonic() + 5
        while mgr.resident() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(mgr.resident(), [])
        self.assertEqual(evicted, [("a", "idle")])

    def test_use_cancels_pending_timer(self):
        mgr = ModelManager(policy="auto", idle_unload=1000)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        with mock.patch("promptchain.manager.threading.Timer") as MockTimer:
            with mgr.use("a"):
                pass
            MockTimer.assert_called_once()  # armed on exit
            with mgr.use("a"):
                MockTimer.return_value.cancel.assert_called_once()

    def test_per_model_override_beats_manager_default(self):
        mgr = ModelManager(policy="auto", idle_unload=1000)
        mgr.register("a", Endpoint("lmstudio", "model-a"), idle_unload=0.05)
        with mgr.use("a"):
            pass
        deadline = time.monotonic() + 5
        while mgr.resident() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(mgr.resident(), [])

    def test_zero_idle_never_arms(self):
        mgr = ModelManager(policy="auto", idle_unload=0.0)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        with mock.patch("promptchain.manager.threading.Timer") as MockTimer:
            with mgr.use("a"):
                pass
            MockTimer.assert_not_called()


class TestConcurrency(ManagerTestCase):
    def test_same_model_use_is_serialized(self):
        mgr = ModelManager(policy="auto")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        order = []
        entered = threading.Event()

        def worker():
            entered.set()
            with mgr.use("a"):
                order.append("worker")

        with mgr.use("a"):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            self.assertTrue(entered.wait(timeout=5))
            time.sleep(0.1)  # give the worker a chance to (wrongly) enter
            order.append("main")
        thread.join(timeout=5)
        self.assertEqual(order, ["main", "worker"])
        self.assertEqual(self.load_mock.call_count, 1)  # single load, not two


class TestResidencyReconciliation(ManagerTestCase):
    def test_refresh_updates_belief_and_vram(self):
        mgr = ModelManager(policy="auto")
        mgr.register("chat", Endpoint("ollama", "qwen3:8b"))
        mgr.register("embed", Endpoint("ollama", "nomic-embed-text"))
        mgr.load("chat")
        mgr.load("embed")
        # Server truth: only qwen3 is actually resident (as 'qwen3:8b')
        self.loaded_mock.return_value = [
            {"model": "qwen3:8b", "vram_bytes": 6_000_000_000, "context_length": 40960},
        ]
        results = mgr.refresh_residency()
        self.assertEqual(results, {"chat": True, "embed": False})
        self.assertEqual(mgr.resident(), ["chat"])
        self.assertEqual(mgr.stats()["chat"]["vram_bytes"], 6_000_000_000)

    def test_latest_tag_normalization(self):
        mgr = ModelManager(policy="auto")
        mgr.register("chat", Endpoint("ollama", "llama3"))
        self.loaded_mock.return_value = [
            {"model": "llama3:latest", "vram_bytes": None, "context_length": None},
        ]
        self.assertEqual(mgr.refresh_residency(), {"chat": True})


class TestStatsAndHooks(ManagerTestCase):
    def test_usage_accumulates_into_stats(self):
        mgr = ModelManager(policy="auto")
        mgr.register("reviewer", Endpoint("anthropic", "claude-sonnet-5", api_key="k"))
        fake = StreamingResponse(
            iter(["hi", " there"]),
            {"input_tokens": 5, "output_tokens": 7}, {}, [],
        )
        with mock.patch("promptchain.manager.stream", return_value=fake):
            with mgr.use("reviewer") as m:
                self.assertEqual(m.complete(user_message="hello"), "hi there")
        stats = mgr.stats()["reviewer"]
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["input_tokens"], 5)
        self.assertEqual(stats["output_tokens"], 7)
        self.assertGreater(stats["est_cost"], 0)

    def test_on_load_hook_fires_once_per_transition(self):
        mgr = ModelManager(policy="auto")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        loads = []
        mgr.on_load(loads.append)
        with mgr.use("a"):
            pass
        with mgr.use("a"):  # already resident — no second event
            pass
        self.assertEqual(loads, ["a"])

    def test_hook_exceptions_never_break_lifecycle(self):
        mgr = ModelManager(policy="auto", max_resident=1)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        mgr.on_evict(lambda *a: 1 / 0)
        with mgr.use("a"):
            pass
        with mgr.use("b"):  # eviction of 'a' fires the broken hook
            pass
        self.assertEqual(mgr.resident(), ["b"])

    def test_unload_all(self):
        mgr = ModelManager(policy="auto", max_resident=None)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("ollama", "model-b"))
        mgr.load("a")
        mgr.load("b")
        mgr.unload_all()
        self.assertEqual(mgr.resident(), [])
        self.assertEqual(self.unload_mock.call_count, 2)


class TestFailedUnload(ManagerTestCase):
    """A failed unload (server unreachable) must NOT be recorded as an
    eviction — clearing residency on failure would let _needs_room
    over-commit the GPU, the exact OOM the manager exists to prevent."""

    def test_failed_unload_keeps_residency(self):
        mgr = ModelManager(policy="auto")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        evicted = []
        mgr.on_evict(lambda *args: evicted.append(args))
        with mgr.use("a"):
            pass
        self.unload_mock.return_value = False  # unload request fails
        self.assertFalse(mgr.unload("a"))
        self.assertEqual(mgr.resident(), ["a"])  # belief unchanged
        self.assertEqual(evicted, [])
        self.assertEqual(mgr.stats()["a"]["unloads"], 0)

    def test_make_room_skips_unevictable_victim_without_looping(self):
        mgr = ModelManager(policy="auto", max_resident=1)
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.register("b", Endpoint("lmstudio", "model-b"))
        with mgr.use("a"):
            pass
        self.unload_mock.return_value = False  # eviction of 'a' fails
        self.assertTrue(mgr.load("b"))  # proceeds best-effort, no infinite loop
        self.assertEqual(sorted(mgr.resident()), ["a", "b"])


class TestCustomCloudSafety(ManagerTestCase):
    def test_load_never_pings_custom_endpoints(self):
        """A keyed `custom` endpoint is likely a paid OpenAI-compatible cloud
        (DeepSeek, Groq, ...) — load()/preload() must never fire a JIT
        completion at it."""
        mgr = ModelManager(policy="auto")
        mgr.register("deepseek", Endpoint(
            "custom", "deepseek-chat",
            base_url="https://api.deepseek.com", api_key="sk-x",
        ))
        self.assertFalse(mgr.load("deepseek"))
        thread = mgr.preload("deepseek")
        thread.join(timeout=5)
        self.load_mock.assert_not_called()


class TestStatsAccuracy(ManagerTestCase):
    def test_loads_counts_transitions_not_calls(self):
        mgr = ModelManager(policy="auto")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.load("a")
        mgr.load("a")
        mgr.load("a")
        self.assertEqual(mgr.stats()["a"]["loads"], 1)

    def test_unloads_counts_transitions_not_attempts(self):
        mgr = ModelManager(policy="auto")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        mgr.unload("a")  # was never resident — attempt, not a transition
        self.assertEqual(mgr.stats()["a"]["unloads"], 0)
        mgr.load("a")
        mgr.unload("a")
        self.assertEqual(mgr.stats()["a"]["unloads"], 1)


class TestPreload(ManagerTestCase):
    def test_preload_runs_in_background(self):
        mgr = ModelManager(policy="auto")
        mgr.register("a", Endpoint("lmstudio", "model-a"))
        thread = mgr.preload("a")
        thread.join(timeout=5)
        self.assertEqual(mgr.resident(), ["a"])


if __name__ == "__main__":
    unittest.main()
