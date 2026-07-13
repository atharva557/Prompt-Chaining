"""Model lifecycle: explicit load/unload, loaded-model introspection, and the
legacy single-slot idle-unload timer (kept for the bundled app; ModelManager
has its own per-model timers).

Everything here is best-effort by design: local servers may evict or load
models on their own, so these calls never raise — they return booleans or
empty lists and leave reconciliation to callers (see
ModelManager.refresh_residency).
"""

import re
import threading

import requests

from .backends import (
    DEFAULT_TIMEOUT,
    chat_completions_url,
    is_cloud,
    is_managed,
)

# Loading a big model from disk can legitimately take minutes
LOAD_TIMEOUT = 300

# LM Studio names loaded *instances* "model-key", "model-key:2", ... — strip
# the numeric suffix to recover the model key. (Ollama's colons are tags and
# must NOT go through this.)
_LMS_INSTANCE_SUFFIX = re.compile(r":(\d+)$")


def _lms_model_key(instance_id: str) -> str:
    return _LMS_INSTANCE_SUFFIX.sub("", instance_id)


def unload_model(base_url: str, model_id: str, backend: str = "lmstudio") -> bool:
    """
    Best-effort model unload. Never raises exceptions.
    LM Studio: unloads every loaded *instance* of the model via the native
    /api/v1/models/unload endpoint (verified live: takes {"instance_id": ...};
    a model can have several instances like "key" and "key:2"). TTL=0 trick
    as a last resort for very old versions.
    Ollama: uses keep_alive=0 parameter.
    Custom / cloud: no-op — custom servers have no standardized unload (and the
    TTL trick would *load* the model on llama-swap), and cloud backends have no
    local VRAM to free. Eviction is left to the server / provider.
    Returns True if unload was attempted (not guaranteed to work).
    """
    base_url = base_url.rstrip("/")
    if backend == "custom" or is_cloud(backend):
        return False
    try:
        if backend == "ollama":
            # Ollama: POST /api/generate with keep_alive=0
            payload = {
                "model": model_id,
                "prompt": "",
                "keep_alive": 0
            }
            requests.post(
                f"{base_url}/api/generate",
                json=payload,
                timeout=DEFAULT_TIMEOUT
            )
            return True

        # LM Studio: consult the loaded-instance listing first. Verified live:
        # firing the TTL trick at a model that is NOT loaded *loads* it (the
        # JIT completion pulls it into VRAM, and modern LM Studio ignores
        # ttl=0) — so when the listing works, trust it completely.
        entries = _lms_loaded_entries(base_url)
        if entries is not None:
            instances = [
                entry.get("instance_id") or entry["model"]
                for entry in entries
                if _lms_model_key(entry["model"]) == model_id
            ]
            if not instances:
                return True  # already not loaded — nothing to do
            native_ok = False
            for instance_id in instances:
                try:
                    resp = requests.post(
                        f"{base_url}/api/v1/models/unload",
                        json={"instance_id": instance_id},
                        timeout=DEFAULT_TIMEOUT
                    )
                    native_ok = native_ok or resp.status_code == 200
                except requests.RequestException:
                    pass
            if native_ok:
                return True
            # Listing says loaded but native unload failed (pre-0.4 server):
            # the TTL trick is safe here because the model IS resident.
            return _lms_ttl_unload(base_url, model_id)

        # No usable listing API (very old LM Studio): blind legacy path.
        try:
            resp = requests.post(
                f"{base_url}/api/v1/models/unload",
                json={"instance_id": model_id},
                timeout=DEFAULT_TIMEOUT
            )
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        return _lms_ttl_unload(base_url, model_id)
    except Exception:
        return False  # Best-effort, don't crash


def _lms_ttl_unload(base_url: str, model_id: str) -> bool:
    """Old-LM-Studio fallback: a 1-token completion with ttl=0 evicts the
    model right after. Only call this when the model is (believed) loaded —
    on an unloaded model it does the opposite and loads it."""
    payload = {
        "model": model_id,
        # A real token: empty content breaks some chat templates (Gemma)
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "ttl": 0
    }
    requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        timeout=DEFAULT_TIMEOUT
    )
    return True


def load_model(
    base_url: str,
    model_id: str,
    backend: str = "lmstudio",
    timeout: float = LOAD_TIMEOUT,
    keep_alive=None,
) -> bool:
    """
    Best-effort explicit model load (pre-warming). Never raises. Returns True
    when a load request was accepted; the call blocks until the server has
    the model up (all three paths below are synchronous on the server side).

    Ollama: empty /api/generate loads the model (`keep_alive` forwarded when
    given — beware `-1` pins the model beyond this process's lifetime).
    LM Studio: skipped when an instance is already loaded (the native load
    endpoint spawns a *second* instance otherwise — verified live), else
    native POST /api/v1/models/load {"model": ...}, JIT completion fallback.
    Custom: JIT completion — on llama-swap this *is* the swap trigger.
    Cloud: no-op (nothing to load), returns False.
    """
    base_url = base_url.rstrip("/")
    if is_cloud(backend):
        return False
    try:
        if backend == "ollama":
            payload = {"model": model_id, "prompt": ""}
            if keep_alive is not None:
                payload["keep_alive"] = keep_alive
            resp = requests.post(
                f"{base_url}/api/generate", json=payload, timeout=timeout
            )
            return resp.status_code == 200

        if backend == "lmstudio":
            # Idempotence guard: loading an already-loaded model would spawn
            # an extra instance and double the VRAM use.
            already = any(
                _lms_model_key(entry["model"]) == model_id
                for entry in loaded_models(base_url, "lmstudio")
            )
            if already:
                return True
            # Native load endpoint (verified live: {"model": <key>}, blocks
            # until loaded). Falls through to JIT on any failure.
            try:
                resp = requests.post(
                    f"{base_url}/api/v1/models/load",
                    json={"model": model_id},
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    return True
            except requests.RequestException:
                pass

        # Universal fallback: a 1-token completion JIT-loads the model.
        # A real token, not "" — empty content breaks some chat templates.
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        resp = requests.post(
            chat_completions_url(base_url, backend), json=payload, timeout=timeout
        )
        return resp.status_code == 200
    except Exception:
        return False


def loaded_models(base_url: str, backend: str = "lmstudio") -> list[dict]:
    """
    Best-effort list of models currently resident on a local server. Each
    entry is {"model": str, "instance_id": str | None, "vram_bytes":
    int | None, "context_length": int | None}; "model" is the model key
    (LM Studio instance suffixes like ':2' stripped), "instance_id" the raw
    per-instance handle where the server has one. Empty list for cloud/custom
    backends (no standard API) and on any error — callers must treat absence
    of data as "unknown", not "nothing loaded".
    """
    base_url = base_url.rstrip("/")
    if not is_managed(backend):
        return []
    try:
        if backend == "ollama":
            resp = requests.get(f"{base_url}/api/ps", timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                return []
            out = []
            for m in resp.json().get("models", []):
                name = m.get("model") or m.get("name", "")
                if name:
                    out.append({
                        "model": name,
                        "instance_id": None,
                        "vram_bytes": m.get("size_vram"),
                        "context_length": m.get("context_length"),
                    })
            return out

        entries = _lms_loaded_entries(base_url)
        return entries if entries is not None else []
    except Exception:
        return []


def _lms_loaded_entries(base_url: str) -> list[dict] | None:
    """LM Studio loaded-instance listing, or None when the server exposes no
    usable listing API (so callers can tell 'nothing loaded' apart from
    'cannot know'). /api/v0/models has an explicit per-instance `state` field
    (verified live); /api/v1/models — {"models": [{"key",
    "loaded_instances", ...}]} — is the fallback shape."""
    try:
        resp = requests.get(f"{base_url}/api/v0/models", timeout=DEFAULT_TIMEOUT)
    except requests.RequestException:
        resp = None
    if resp is not None and resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            out = []
            for m in data["data"]:
                if not isinstance(m, dict):
                    continue
                state = str(m.get("state", "")).lower()
                if state == "loaded" and m.get("id"):
                    out.append({
                        "model": _lms_model_key(m["id"]),
                        "instance_id": m["id"],
                        "vram_bytes": None,
                        "context_length": m.get("loaded_context_length")
                        or m.get("max_context_length"),
                    })
            return out

    try:
        resp = requests.get(f"{base_url}/api/v1/models", timeout=DEFAULT_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return None
    out = []
    for m in data["models"]:
        if not isinstance(m, dict) or not m.get("key"):
            continue
        for instance in m.get("loaded_instances") or []:
            instance_id = (
                instance.get("instance_id") if isinstance(instance, dict)
                else str(instance)
            )
            out.append({
                "model": m["key"],
                "instance_id": instance_id,
                "vram_bytes": None,
                "context_length": m.get("max_context_length"),
            })
    return out


# ── Legacy idle / deferred model unload (single global slot) ────────────────
# A single process-wide background timer that frees a local model's VRAM after
# an idle period. Kept for the bundled Streamlit app, which re-arms it on
# every rerun; new code should prefer ModelManager's per-model idle timers.
# The callback only calls unload_model (pure HTTP) — it never touches UI
# state; it records that it fired and the app polls consume_unload_fired().
_unload_timer: "threading.Timer | None" = None
_unload_fired = False
_unload_lock = threading.Lock()


def _fire_unload(base_url: str, model_id: str, backend: str) -> None:
    """Timer callback: unload the model, then record that the eviction
    happened so the next script run can sync its session state."""
    global _unload_timer, _unload_fired
    unload_model(base_url, model_id, backend)
    with _unload_lock:
        _unload_fired = True
        _unload_timer = None


def consume_unload_fired() -> bool:
    """True exactly once after a scheduled unload has actually run."""
    global _unload_fired
    with _unload_lock:
        fired = _unload_fired
        _unload_fired = False
        return fired


def cancel_unload() -> None:
    """Cancel any pending scheduled unload (e.g. a generation is starting)."""
    global _unload_timer
    with _unload_lock:
        if _unload_timer is not None:
            _unload_timer.cancel()
            _unload_timer = None


def schedule_unload(
    base_url: str, model_id: str, backend: str = "lmstudio", delay_seconds: float = 300
) -> bool:
    """
    Arm a background timer to unload a local model after `delay_seconds`.

    Re-arming cancels the previous timer, so calling this on every interaction
    acts as "reset the idle clock". No-op (and cancels) for cloud/custom backends
    or `delay_seconds <= 0` (the latter is how the user disables auto-unload).
    Returns True only when a timer was actually armed.
    """
    global _unload_timer
    with _unload_lock:
        if _unload_timer is not None:
            _unload_timer.cancel()
            _unload_timer = None
        if not delay_seconds or delay_seconds <= 0 or backend == "custom" or is_cloud(backend):
            return False
        timer = threading.Timer(
            delay_seconds, _fire_unload, args=(base_url, model_id, backend)
        )
        timer.daemon = True
        timer.start()
        _unload_timer = timer
        return True
