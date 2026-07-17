# promptchain

**Load, unload, and swap any number of local LLMs on one GPU — with full, explicit control.** A small library for driving LM Studio, Ollama, and any OpenAI-compatible server from Python, plus unified streaming across local *and* cloud backends, and an MCP server so agents can manage your VRAM for you.

Servers already handle the *automatic* case — LM Studio auto-evicts, Ollama's `keep_alive` expires, llama-swap proxies swapping for the servers it manages. What none of them give you is **one client that spans LM Studio + Ollama + any OpenAI-compatible endpoint with a policy engine on top**: pin a model so it's never evicted, pre-warm the next one before you need it, swap a whole working set in one call, cap residency by count or VRAM budget — and hand all of that to your agent over MCP.

```bash
pip install promptchain
```

## Quickstart

```python
from promptchain import ModelManager, Endpoint

# One GPU, one model resident at a time; evict after 5 min idle.
mgr = ModelManager(policy="auto", max_resident=1, idle_unload=300)

mgr.register("drafter", Endpoint("lmstudio", "gemma-4-4b"))
mgr.register("coder",   Endpoint("ollama", "qwen3-coder:30b"), priority=10)
mgr.register("reviewer", Endpoint("anthropic", "claude-sonnet-5"))  # cloud: never counts against VRAM

with mgr.use("coder") as m:            # evicts 'drafter' first if needed, loads 'coder'
    for token in m.stream(user_message="write fizzbuzz in rust"):
        print(token, end="", flush=True)

mgr.resident()        # -> ["coder"]
```

## Full control over the GPU

```python
mgr.load("coder", wait=True)        # pre-warm, block until the server reports it ready
mgr.preload("critic")               # pre-warm in the background
mgr.swap("drafter", "coder")        # atomic unload -> load in one call
mgr.pin("coder"); mgr.unpin("coder")# pinned models are never auto-evicted
mgr.group("review", ["critic", "fixer"])
mgr.activate("review")              # swap a whole working set in; evict everything else
mgr.unload_all()

mgr.refresh_residency()             # reconcile belief with the server (Ollama /api/ps, LM Studio REST)
mgr.stats()                         # per-model loads, evictions, tokens, est. cost
```

- **`policy="auto"`** evicts other models as needed before a load — lowest `priority` first, least-recently-used as the tiebreak — under `max_resident` and/or `vram_budget`.
- **`policy="manual"`** never loads or unloads implicitly; you drive every lifecycle change yourself.
- **Cloud and `custom` backends** stream normally but never count against VRAM and are never evicted.

## Unified streaming

One `stream()` across every backend, returning a handle you iterate for tokens:

```python
from promptchain import stream

resp = stream(backend="ollama", model="qwen3:8b", base_url="http://localhost:11434",
              user_message="explain async/await")
text = resp.consume()
resp.usage        # {"input_tokens": ..., "output_tokens": ...} (cloud backends)
resp.reasoning    # hidden <think>...</think> reasoning, stripped from the visible text
resp.tool_calls   # parsed tool calls when tools= was passed
```

Reasoning models (DeepSeek-R1 / Qwen3 / GLM) have their `<think>` blocks stripped automatically; Hermes-format `<tool_call>` tags are parsed out for local tool calling.

## Backends

| Backend | Load / unload / `ps` | Streaming | Usage reporting |
|---|:---:|:---:|:---:|
| `lmstudio` | ✅ | ✅ | — |
| `ollama` | ✅ | ✅ | — |
| `custom` (llama.cpp, vLLM, llama-swap, Jan, **and any OpenAI-compatible cloud**) | — | ✅ | ✅ (when keyed) |
| `openai` | n/a | ✅ | ✅ |
| `gemini` | n/a | ✅ | ✅ |
| `anthropic` | n/a | ✅ | ✅ |

API keys for the named clouds are read from `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`. Install Anthropic support with `pip install "promptchain[anthropic]"` (OpenAI/Gemini need no extra — they're OpenAI-compatible).

### Any OpenAI-compatible provider

Point the `custom` backend at any OpenAI-compatible endpoint and pass a key — DeepSeek, Groq, Together, Fireworks, OpenRouter, Mistral, DeepInfra, an authenticated vLLM, whatever:

```python
Endpoint("custom", "deepseek-chat",   base_url="https://api.deepseek.com",  api_key="sk-...")
Endpoint("custom", "llama-3.3-70b",   base_url="https://api.groq.com/openai", api_key="gsk-...")
Endpoint("custom", "anthropic/claude-sonnet-4", base_url="https://openrouter.ai/api", api_key="sk-or-...")
```

Set `base_url` to the part before `/v1` — the library appends `/v1/chat/completions`. Token usage is reported whenever a key is present.

## Let an agent manage your GPU (MCP)

```bash
pip install "promptchain[mcp]"
promptchain-mcp        # stdio MCP server
```

Wire it into Hermes Agent, Claude Code, or Claude Desktop and it can `ps` your GPU, `load`/`unload`/`swap` models, and `generate` through them — in plain language. Models are configured in an `endpoints.toml` (auto-created on first run). See the [agent setup guide](https://github.com/atharva557/Prompt-Chaining/blob/master/examples/agent_mcp_setup.md).

## The app built on this

The same repo ships the **PromptChain app** — a two-model Streamlit pipeline with a *human review gate*: a small local model drafts your prompt, you fix it, then the big (local or cloud) model writes the code. It's the flagship consumer of this library; clone the repo to run it.

## Links

- **Source, the app, examples, and full docs:** https://github.com/atharva557/Prompt-Chaining
- Requires Python ≥ 3.10. MIT licensed.
