"""ModelManager — explicit, deterministic control over which models occupy
your GPU.

Register any number of named models across LM Studio / Ollama / OpenAI-
compatible / cloud backends, then either let the manager make room
automatically (``policy="auto"``: priority+LRU eviction under ``max_resident``
and/or ``vram_budget``) or drive every load/unload/swap yourself
(``policy="manual"``). Cloud and ``custom`` backends stream normally but are
never counted against residency and never evicted — there is nothing to
manage there.

Residency tracking is *best-effort by design*: servers can load and evict on
their own, so ``resident()`` reflects the manager's belief and
``refresh_residency()`` reconciles it against server truth (Ollama
``/api/ps``, LM Studio's REST model list). The manager is single-process —
two processes sharing a GPU cannot coordinate through it.
"""

import threading
import time
from contextlib import contextmanager

from . import lifecycle
from .costs import estimate_cost, parse_size
from .endpoint import Endpoint
from .errors import ModelNotRegistered, ModelNotResident
from .streaming import DEFAULT_STREAM_TIMEOUT, StreamingResponse, stream

# How long load(wait=True) polls the server's loaded-model list before
# declaring the verification inconclusive.
WAIT_VERIFY_TIMEOUT = 15.0


def _normalize_model_id(model: str) -> str:
    """Ollama treats 'name' and 'name:latest' as the same model."""
    return model[: -len(":latest")] if model.endswith(":latest") else model


class _Registration:
    """Internal per-model state. All mutation happens under the manager lock;
    request_lock serializes generations/loads against the same model."""

    def __init__(self, endpoint: Endpoint, priority: int,
                 idle_unload: float | None, pinned: bool):
        self.endpoint = endpoint
        self.priority = priority
        self.idle_unload = idle_unload  # None → manager default
        self.pinned = pinned
        self.resident = False
        self.last_used = 0.0
        self.vram_bytes = endpoint.vram_bytes  # hint; refreshed from /api/ps
        self.timer: threading.Timer | None = None
        self.timer_gen = 0  # invalidates in-flight timer callbacks
        self.request_lock = threading.RLock()
        self.stats = {
            "loads": 0, "unloads": 0, "requests": 0,
            "input_tokens": 0, "output_tokens": 0, "est_cost": 0.0,
        }


class BoundModel:
    """Handle yielded by :meth:`ModelManager.use` — a model that is loaded
    (or loading is the caller's responsibility under manual policy) and whose
    idle timer is paused for the duration of the ``with`` block."""

    def __init__(self, manager: "ModelManager", name: str, reg: _Registration):
        self._manager = manager
        self.name = name
        self._reg = reg
        self._responses: list[StreamingResponse] = []

    @property
    def endpoint(self) -> Endpoint:
        return self._reg.endpoint

    def stream(
        self,
        messages: list[dict] | None = None,
        system_prompt: str = "",
        user_message: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: int = DEFAULT_STREAM_TIMEOUT,
        tools: list[dict] | None = None,
        tool_choice=None,
    ) -> StreamingResponse:
        """Stream a generation from this model. Consume the response inside
        the ``with mgr.use(...)`` block so usage lands in the stats."""
        ep = self._reg.endpoint
        response = stream(
            base_url=ep.base_url,
            model=ep.model,
            backend=ep.backend,
            api_key=ep.api_key,
            messages=messages,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            tools=tools,
            tool_choice=tool_choice,
        )
        self._responses.append(response)
        return response

    def complete(self, **kwargs) -> str:
        """Convenience: run :meth:`stream` to completion, return the text."""
        return self.stream(**kwargs).consume()


class ModelManager:
    """Registry + lifecycle policy for any number of models on shared VRAM.

    Args:
        policy: ``"auto"`` evicts other models as needed before a load;
            ``"manual"`` never loads or unloads implicitly — ``use()`` on a
            non-resident model raises :class:`ModelNotResident`.
        max_resident: cap on simultaneously-loaded *managed* models
            (LM Studio/Ollama). ``None`` = uncapped. Default 1 — the
            single-GPU case.
        vram_budget: optional size cap ('20GiB', bytes int). Models with
            unknown size count as 0 — advisory unless sizes are known (Ollama
            reports them; use ``Endpoint(vram_hint=...)`` elsewhere).
        idle_unload: seconds of inactivity before a model is evicted
            (0 = never). Overridable per model at ``register()``.
    """

    def __init__(self, policy: str = "auto", max_resident: int | None = 1,
                 vram_budget=None, idle_unload: float = 0.0):
        if policy not in ("auto", "manual"):
            raise ValueError("policy must be 'auto' or 'manual'")
        self.policy = policy
        self.max_resident = max_resident
        self.vram_budget = parse_size(vram_budget)
        self.idle_unload = idle_unload
        self._registry: dict[str, _Registration] = {}
        self._groups: dict[str, list[str]] = {}
        self._lock = threading.RLock()
        self._on_load: list = []
        self._on_evict: list = []

    # ── Registry ─────────────────────────────────────────────────────────

    def register(self, name: str, endpoint: Endpoint, *, priority: int = 0,
                 idle_unload: float | None = None, pinned: bool = False) -> None:
        """Register a named model. Higher `priority` survives eviction longer."""
        with self._lock:
            if name in self._registry:
                raise ValueError(f"Model '{name}' is already registered.")
            self._registry[name] = _Registration(endpoint, priority, idle_unload, pinned)

    def unregister(self, name: str) -> None:
        """Forget a model (does not unload it — call unload() first if wanted)."""
        with self._lock:
            reg = self._get(name)
            self._cancel_timer(reg)
            del self._registry[name]
            for members in self._groups.values():
                if name in members:
                    members.remove(name)

    def names(self) -> list[str]:
        with self._lock:
            return list(self._registry)

    def endpoint(self, name: str) -> Endpoint:
        with self._lock:
            return self._get(name).endpoint

    def _get(self, name: str) -> _Registration:
        reg = self._registry.get(name)
        if reg is None:
            raise ModelNotRegistered(
                f"Model '{name}' is not registered. Known: {sorted(self._registry)}"
            )
        return reg

    # ── Pinning & groups ─────────────────────────────────────────────────

    def pin(self, name: str) -> None:
        """A pinned model is never auto-evicted (explicit unload still works)."""
        with self._lock:
            self._get(name).pinned = True

    def unpin(self, name: str) -> None:
        with self._lock:
            self._get(name).pinned = False

    def group(self, group_name: str, members: list[str]) -> None:
        """Define a named working set for :meth:`activate`."""
        with self._lock:
            for member in members:
                self._get(member)  # validate
            self._groups[group_name] = list(members)

    def activate(self, group_name: str, wait: bool = True) -> dict[str, bool]:
        """Swap a whole working set in: evict every resident managed model
        outside the group (pinned models survive), then load the members in
        order. Returns {member: loaded_ok}. Explicit — works in both policies."""
        with self._lock:
            if group_name not in self._groups:
                raise KeyError(f"No group named '{group_name}'.")
            members = list(self._groups[group_name])
            to_evict = [
                n for n, r in self._registry.items()
                if r.resident and r.endpoint.is_managed
                and not r.pinned and n not in members
            ]
        for name in to_evict:
            self.unload(name)
        return {name: self.load(name, wait=wait) for name in members}

    # ── Lifecycle ────────────────────────────────────────────────────────

    def load(self, name: str, wait: bool = True,
             timeout: float = lifecycle.LOAD_TIMEOUT) -> bool:
        """Explicitly load (pre-warm) a model. Under auto policy this evicts
        others first as needed; under manual policy it loads exactly this
        model and nothing else changes. No-op (False) for cloud backends."""
        reg = self._get(name)
        ep = reg.endpoint
        if not ep.is_local:
            return False
        if self.policy == "auto" and ep.is_managed:
            self._make_room(name)
        with reg.request_lock:
            ok = lifecycle.load_model(ep.base_url, ep.model, ep.backend, timeout=timeout)
            if ok and wait and ep.is_managed:
                self._wait_for_residency(ep)
            with self._lock:
                if ok:
                    was_resident = reg.resident
                    reg.resident = True
                    reg.last_used = time.monotonic()
                    reg.stats["loads"] += 1
            if ok and not was_resident:
                self._emit(self._on_load, name)
        return ok

    def preload(self, name: str) -> threading.Thread:
        """Background pre-warm: kick off load() on a daemon thread and return
        it. Typical use: start loading the pipeline's next model while the
        current one is still streaming."""
        thread = threading.Thread(
            target=self._preload_quietly, args=(name,),
            name=f"promptchain-preload-{name}", daemon=True,
        )
        thread.start()
        return thread

    def _preload_quietly(self, name: str) -> None:
        try:
            self.load(name)
        except Exception:
            pass  # pre-warming is opportunistic; the real load happens at use()

    def unload(self, name: str) -> bool:
        """Explicitly unload a model (works even when pinned — pinning only
        guards against *automatic* eviction). Best-effort, never raises."""
        reg = self._get(name)
        ep = reg.endpoint
        if not ep.is_managed:
            return False
        with reg.request_lock:  # never yank a model mid-generation
            self._cancel_timer(reg)
            return self._do_unload(name, reg, reason="explicit")

    def unload_all(self) -> None:
        """Unload every managed registered model (e.g. an atexit hook)."""
        for name in self.names():
            try:
                self.unload(name)
            except ModelNotRegistered:
                pass

    def swap(self, unload_name: str, load_name: str, wait: bool = True) -> bool:
        """Atomic ordered unload→load in one call. Explicit — works in both
        policies. Returns the load's success."""
        self.unload(unload_name)
        return self.load(load_name, wait=wait)

    # ── Using a model ────────────────────────────────────────────────────

    @contextmanager
    def use(self, name: str):
        """Acquire a model for one or more generations.

        Pauses the model's idle timer, ensures it is resident (loading it
        under auto policy; raising :class:`ModelNotResident` under manual),
        serializes concurrent users of the same model, and re-arms the idle
        timer + records usage stats on exit. Yields a :class:`BoundModel`.
        """
        reg = self._get(name)
        reg.request_lock.acquire()
        bound = None
        try:
            self._cancel_timer(reg)
            if reg.endpoint.is_managed:
                with self._lock:
                    resident = reg.resident
                if not resident:
                    if self.policy == "manual":
                        raise ModelNotResident(
                            f"Model '{name}' is not loaded and policy='manual' "
                            f"forbids implicit loads. Call load('{name}') first."
                        )
                    self._make_room(name)
                    ok = lifecycle.load_model(
                        reg.endpoint.base_url, reg.endpoint.model, reg.endpoint.backend
                    )
                    with self._lock:
                        reg.resident = bool(ok) or reg.resident
                        if ok:
                            reg.stats["loads"] += 1
                    if ok:
                        self._emit(self._on_load, name)
            bound = BoundModel(self, name, reg)
            yield bound
        finally:
            with self._lock:
                reg.last_used = time.monotonic()
                reg.stats["requests"] += 1
                if bound is not None:
                    self._accumulate_usage(reg, bound)
            self._arm_timer(name, reg)
            reg.request_lock.release()

    def _accumulate_usage(self, reg: _Registration, bound: BoundModel) -> None:
        for response in bound._responses:
            usage = response.usage
            tokens_in = usage.get("input_tokens")
            tokens_out = usage.get("output_tokens")
            if tokens_in:
                reg.stats["input_tokens"] += tokens_in
            if tokens_out:
                reg.stats["output_tokens"] += tokens_out
            cost = estimate_cost(reg.endpoint.model, tokens_in, tokens_out)
            if cost:
                reg.stats["est_cost"] += cost

    # ── Eviction (auto policy) ───────────────────────────────────────────

    def _needs_room(self, incoming: str) -> bool:
        """Caller holds self._lock. Would loading `incoming` violate the caps?"""
        reg = self._registry[incoming]
        others = [
            r for n, r in self._registry.items()
            if n != incoming and r.resident and r.endpoint.is_managed
        ]
        count = len(others) + 1
        if self.max_resident is not None and count > self.max_resident:
            return True
        if self.vram_budget is not None:
            total = sum(r.vram_bytes or 0 for r in others) + (reg.vram_bytes or 0)
            if total > self.vram_budget:
                return True
        return False

    def _make_room(self, incoming: str) -> None:
        """Evict unpinned managed models — lowest priority first, LRU as
        tiebreak — until `incoming` fits. Best-effort: models that are busy
        (mid-generation) or pinned are skipped, and if nothing evictable
        remains the load proceeds anyway."""
        skipped: set[str] = set()
        while True:
            with self._lock:
                if not self._needs_room(incoming):
                    return
                candidates = sorted(
                    (
                        (r.priority, r.last_used, n)
                        for n, r in self._registry.items()
                        if n != incoming and n not in skipped
                        and r.resident and r.endpoint.is_managed and not r.pinned
                    ),
                )
                if not candidates:
                    return  # nothing evictable — proceed best-effort
                victim = candidates[0][2]
                victim_reg = self._registry[victim]
            # Don't unload a model that is mid-generation: skip busy victims.
            if victim_reg.request_lock.acquire(timeout=0.1):
                try:
                    self._cancel_timer(victim_reg)
                    self._do_unload(victim, victim_reg, reason="evicted")
                finally:
                    victim_reg.request_lock.release()
            else:
                skipped.add(victim)

    def _do_unload(self, name: str, reg: _Registration, reason: str) -> bool:
        """Caller holds reg.request_lock."""
        ep = reg.endpoint
        ok = lifecycle.unload_model(ep.base_url, ep.model, ep.backend)
        with self._lock:
            was_resident = reg.resident
            reg.resident = False
            reg.stats["unloads"] += 1
        if was_resident:
            self._emit(self._on_evict, name, reason)
        return ok

    # ── Idle timers (one per model) ──────────────────────────────────────

    def _arm_timer(self, name: str, reg: _Registration) -> None:
        delay = reg.idle_unload if reg.idle_unload is not None else self.idle_unload
        if not delay or delay <= 0 or not reg.endpoint.is_managed:
            return
        with self._lock:
            if not reg.resident:
                return
            reg.timer_gen += 1
            generation = reg.timer_gen
            timer = threading.Timer(delay, self._idle_fire, args=(name, generation))
            timer.daemon = True
            reg.timer = timer
            timer.start()

    def _cancel_timer(self, reg: _Registration) -> None:
        with self._lock:
            reg.timer_gen += 1  # invalidate any in-flight callback
            if reg.timer is not None:
                reg.timer.cancel()
                reg.timer = None

    def _idle_fire(self, name: str, generation: int) -> None:
        with self._lock:
            reg = self._registry.get(name)
            if reg is None or generation != reg.timer_gen:
                return  # cancelled or superseded
            reg.timer = None
        # Never evict mid-generation; if busy, use() re-arms on exit anyway.
        if reg.request_lock.acquire(blocking=False):
            try:
                self._do_unload(name, reg, reason="idle")
            finally:
                reg.request_lock.release()

    # ── Introspection ────────────────────────────────────────────────────

    def resident(self) -> list[str]:
        """Names the manager believes are currently loaded (managed only)."""
        with self._lock:
            return [
                n for n, r in self._registry.items()
                if r.resident and r.endpoint.is_managed
            ]

    def refresh_residency(self) -> dict[str, bool]:
        """Reconcile the manager's belief with server truth (Ollama /api/ps,
        LM Studio REST). Also refreshes VRAM sizes where the server reports
        them. Pure bookkeeping — fires no callbacks. Returns {name: resident}."""
        with self._lock:
            servers: dict[tuple[str, str], list[str]] = {}
            for name, reg in self._registry.items():
                if reg.endpoint.is_managed:
                    servers.setdefault(
                        (reg.endpoint.base_url, reg.endpoint.backend), []
                    ).append(name)
        results: dict[str, bool] = {}
        for (base_url, backend), names in servers.items():
            loaded = lifecycle.loaded_models(base_url, backend)
            by_id = {
                _normalize_model_id(entry["model"]): entry for entry in loaded
            }
            with self._lock:
                for name in names:
                    reg = self._registry.get(name)
                    if reg is None:
                        continue
                    entry = by_id.get(_normalize_model_id(reg.endpoint.model))
                    reg.resident = entry is not None
                    if entry and entry.get("vram_bytes"):
                        reg.vram_bytes = entry["vram_bytes"]
                    results[name] = reg.resident
        return results

    def stats(self) -> dict[str, dict]:
        """Per-model counters: loads, unloads, requests, tokens, est. cost,
        residency, and seconds since last use."""
        now = time.monotonic()
        with self._lock:
            return {
                name: {
                    **reg.stats,
                    "resident": reg.resident,
                    "pinned": reg.pinned,
                    "priority": reg.priority,
                    "backend": reg.endpoint.backend,
                    "model": reg.endpoint.model,
                    "vram_bytes": reg.vram_bytes,
                    "idle_seconds": (now - reg.last_used) if reg.last_used else None,
                }
                for name, reg in self._registry.items()
            }

    # ── Hooks ────────────────────────────────────────────────────────────

    def on_load(self, callback) -> None:
        """callback(name) — fires after a model becomes resident."""
        self._on_load.append(callback)

    def on_evict(self, callback) -> None:
        """callback(name, reason) — reason is 'evicted', 'idle', or 'explicit'."""
        self._on_evict.append(callback)

    def _emit(self, callbacks: list, *args) -> None:
        for callback in list(callbacks):
            try:
                callback(*args)
            except Exception:
                pass  # user hooks must never break lifecycle operations

    # ── Internals ────────────────────────────────────────────────────────

    def _wait_for_residency(self, endpoint: Endpoint,
                            timeout: float = WAIT_VERIFY_TIMEOUT) -> None:
        """Poll the server's loaded list until the model shows up (or the
        verification window closes — inconclusive is not a failure, since
        load_model() already blocked until the server answered)."""
        target = _normalize_model_id(endpoint.model)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            listed = lifecycle.loaded_models(endpoint.base_url, endpoint.backend)
            if not listed:
                return  # server gave no data — can't verify, don't block
            if any(_normalize_model_id(e["model"]) == target for e in listed):
                return
            time.sleep(0.5)
