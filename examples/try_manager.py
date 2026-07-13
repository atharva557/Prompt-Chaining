"""Hands-on manual test of ModelManager against your real LM Studio server.

Watch LM Studio's "loaded models" panel (or Developer tab) while this runs —
you'll SEE the first model get evicted when the second one loads, because
max_resident=1 means only one may sit on the GPU at a time.

Run it:
    python examples/try_manager.py

Edit MODEL_A / MODEL_B below if these model ids aren't on your machine
(run `list_models` or check LM Studio to see what you have).
"""

from promptchain import Endpoint, ModelManager

# Two small models that both live on your LM Studio server (localhost:1234).
MODEL_A = "google/gemma-4-e4b"
MODEL_B = "liquid/lfm2.5-1.2b"


def show(mgr, label):
    print(f"\n--- {label} ---")
    print("  manager believes resident:", mgr.resident())
    print("  server actually reports:  ", mgr.refresh_residency())


def main():
    # max_resident=1 → a single-GPU "one model at a time" desk.
    mgr = ModelManager(policy="auto", max_resident=1)
    mgr.register("a", Endpoint("lmstudio", MODEL_A))
    mgr.register("b", Endpoint("lmstudio", MODEL_B))

    # See what (if anything) is already loaded before we touch anything.
    show(mgr, "start")

    print(f"\n>>> using 'a' ({MODEL_A}) — it loads on demand")
    with mgr.use("a") as m:
        reply = m.complete(user_message="Reply with exactly: HELLO FROM A",
                           max_tokens=20)
        print("  model said:", reply.strip())
    show(mgr, "after using 'a'")

    print(f"\n>>> using 'b' ({MODEL_B}) — watch 'a' get EVICTED to make room")
    with mgr.use("b") as m:
        reply = m.complete(user_message="Reply with exactly: HELLO FROM B",
                           max_tokens=20)
        print("  model said:", reply.strip())
    show(mgr, "after using 'b' (a should be gone)")

    print("\n>>> unload everything (free the GPU)")
    mgr.unload_all()
    show(mgr, "after unload_all")

    print("\n--- per-model stats ---")
    for name, s in mgr.stats().items():
        print(f"  {name}: loads={s['loads']} unloads={s['unloads']} "
              f"requests={s['requests']} tokens_out={s['output_tokens']}")


if __name__ == "__main__":
    main()
