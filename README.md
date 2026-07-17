<div align="center">

# 🔗 PromptChain

**Control what's loaded on your GPU — from Python, from your coding agent, or from a pipeline with a human in the loop.**

A pip-installable library + MCP server for explicit local-model lifecycle control, and a two-model Streamlit app built on top of it.

[![PyPI](https://img.shields.io/pypi/v/promptchain?color=3775A9&logo=pypi&logoColor=white)](https://pypi.org/project/promptchain/)
[![CI](https://github.com/atharva557/Prompt-Chaining/actions/workflows/ci.yml/badge.svg)](https://github.com/atharva557/Prompt-Chaining/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Local-first, cloud optional](https://img.shields.io/badge/local--first-cloud_optional-blueviolet)](#)

</div>

---

This repo is **two things, one stack**:

| | What | Get it |
|---|---|---|
| 📦 | **`promptchain` — the library + MCP server.** Load, unload, swap, and pin any number of local models (LM Studio, Ollama) with full client-side control — and expose that control to agents like Claude Code or Hermes Agent over MCP. | `pip install promptchain` · [PyPI](https://pypi.org/project/promptchain/) · [library README](README-pypi.md) |
| 🔗 | **The PromptChain app — a two-model pipeline with a human review gate.** A small local model drafts your prompt, *you fix it*, then the big (local or cloud) model writes the code. Built on the library. | clone this repo → [Quick start](#-the-app-a-pipeline-with-a-review-gate) |

---

## 📦 The library: your GPU, your rules — even for your agent

**Honest context first:** if all you want is "call model A, then model B, and have them swap automatically," you don't need this — LM Studio's JIT + auto-evict does it by default and Ollama's `keep_alive` manages itself. [llama-swap](https://github.com/mostlygeek/llama-swap) goes further with explicit unload endpoints, `/running`, and groups — for the llama.cpp-style servers it proxies. Single-backend MCP servers exist too ([vram-mcp](https://glama.ai/mcp/servers/sushiHex/vram-mcp) for Ollama, [lmstudio-mcp](https://github.com/seajhawk/lmstudio-mcp) for LM Studio).

What `promptchain` adds is the combination none of them ship: **one client — and one MCP server — that spans LM Studio + Ollama + any OpenAI-compatible endpoint, with a policy engine instead of raw load/unload calls**:

- **`ps` across servers** — one view of what's resident on Ollama *and* LM Studio, with VRAM
- **Pin** a model so it's never evicted · **preload** the next one before you need it
- **Swap whole working sets** in one call (`group` / `activate`) · cap by count or **VRAM budget**
- **`policy="manual"`** — nothing loads or unloads unless you say so
- Unified streaming with reasoning-model (`<think>`) and Hermes tool-call handling, across local servers, OpenAI/Claude/Gemini, and **any OpenAI-compatible cloud** (DeepSeek, Groq, OpenRouter, …)

```python
from promptchain import ModelManager, Endpoint

mgr = ModelManager(policy="auto", max_resident=1, idle_unload=300)
mgr.register("drafter", Endpoint("lmstudio", "gemma-4-4b"))
mgr.register("coder",   Endpoint("ollama", "qwen3-coder:30b"), priority=10)

with mgr.use("coder") as m:                     # drafter is evicted first if needed
    for tok in m.stream(user_message="fizzbuzz in rust"):
        print(tok, end="", flush=True)
```

### 🤖 The wedge: your agent manages its own GPU — across every backend

As coding agents get pointed at local models, someone has to decide what's worth keeping in VRAM — and today that's either a server heuristic or you, alt-tabbing. `promptchain-mcp` gives the **agent** the tools instead:

```bash
pip install "promptchain[mcp]"
claude mcp add promptchain -- promptchain-mcp     # or Hermes Agent / Claude Desktop
```

Then just ask: *"what's on my GPU?"* → `ps` · *"free the GPU before you build"* → `unload_all` · *"pre-warm the coder model"* → `load_model` · *"run this through the local drafter"* → `generate`.

➡️ Setup for Hermes Agent, Claude Code, and Claude Desktop: [examples/agent_mcp_setup.md](examples/agent_mcp_setup.md)

---

## 🔗 The app: a pipeline with a review gate

**See what the small model wrote. Fix it. *Then* spend the expensive call.**

Most model chains are fire-and-forget: if the intermediate prompt is mediocre, you pay for a mediocre generation and re-roll. PromptChain stops the pipeline at the point where a human is cheapest and most useful — between the draft and the expensive generation:

```
you type a rough idea
        ▼
Prompter (small, local, free)  →  drafts a detailed prompt
        ▼
🧍 YOU — review · edit · revise · retry        ← the review gate
        ▼
Coder (large — local or cloud) →  streams the code
        ▼
per-file tabs · refine in place · diff every version · revert · save
```

Each role has its own backend, so the classic setup is a **free local Prompter + a frontier cloud Coder** (OpenAI / Claude / Gemini / DeepSeek / …): the free review gate means the one paid generation lands right more often, so you re-roll far less. Fully local works too — the library underneath swaps VRAM between the two models automatically on GPUs that only fit one.

### Features

|    | Feature                          | Details                                                                                                                                 |
| --- | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 🧍  | **Review gate**                  | Edit, revise (multi-turn), or retry the drafted prompt before generation — with a diff of idea → prompt. **Quick mode** skips it when you don't care |
| ♻️ | **Refine loop**                  | "Make the board bigger" edits the generated code in place; every version is diffed and revertible in one click                          |
| 📡  | **Real-time streaming**          | Token-by-token with live tok/s; exact billed tokens + cost estimate for cloud generations                                               |
| 🤔  | **Reasoning models welcome**     | `<think>` blocks and reasoning deltas (Qwen3 / DeepSeek-R1 style) stream into a collapsed panel — never into your prompt or code        |
| 🔌  | **Per-role backends**            | Mix local and cloud: LM Studio, Ollama, any OpenAI-compatible server or cloud, plus OpenAI, Claude, Gemini — chosen per role            |
| 🗂️ | **Multi-file output**            | Fenced blocks become per-file tabs with zip download / save-all; language detection and filename suggestions                            |
| 📋  | **46 built-in presets**          | System-prompt pairs across web, games, data, systems, testing, debugging, languages, ML — editable, with overrides and custom presets   |
| 💡  | **Preset auto-suggestion**       | Task keywords suggest a matching Prompter + Coder pair, applied in one click                                                            |
| 🎛️ | **Pipeline profiles**            | Save the whole setup (backends, models, params, system prompts) under a name; switch in one click                                       |
| 💬  | **Direct chats**                 | ChatGPT-style pages for either model; persistent; any chat-drafted prompt jumps straight into the pipeline                              |
| 🛡️ | **Context guards**               | Warns before a refine payload or pasted-code task outgrows a small local context window                                                 |
| 🕘  | **Run history**                  | Past runs persist; reopen or delete from the sidebar. **No telemetry.**                                                                 |

### 🚀 Quick start

You only need **Python 3.10+** ([python.org](https://www.python.org/downloads/) — on Windows, tick *"Add Python to PATH"*).

**Option A — double-click:** download/clone the repo, then run `run.bat` (Windows), `run.command` (macOS), or `run.sh` (Linux). First launch sets up everything and opens the app in your browser.

**Option B — terminal:**

```bash
git clone https://github.com/atharva557/Prompt-Chaining.git
cd Prompt-Chaining
pip install -r requirements.txt
streamlit run app.py
```

On first launch the Settings page opens with your installed models auto-detected — pick two and save. Tests: `pip install -r requirements-dev.txt && pytest` (220+ tests).

### ⚙️ Configuration

Each role (Prompter / Coder) is configured independently in **Settings**:

| Setting                | Default       | Notes                                                                                                                          |
| ---------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Backend (per role)     | LM Studio     | LM Studio, Ollama, Custom (OpenAI-compatible, local or cloud), OpenAI, Anthropic, Gemini                                       |
| Base URL (per role)    | per-backend   | Editable for local/custom backends; fixed for the named clouds                                                                 |
| Model (per role)       | —             | Auto-detected from the server, or entered manually                                                                             |
| Temperature / max tokens | 0.3 / 0.1 · 1024 / 4096 | Per role                                                                                                             |
| Output folder          | `./output`    | Multi-file runs get a timestamped subfolder                                                                                    |
| Idle auto-unload       | 5 min         | Free local VRAM when the resident model sits idle (`0` = never)                                                                |
| VRAM swap policy       | auto          | *Auto* unloads one model before running the other; *never* if your GPU holds both                                              |

**API keys** are read from env vars first (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`), falling back to Settings. Everything persists in `config.json` (git-ignored).

### 🤖 Recommended models

| Role | Model | VRAM | Notes |
|---|---|---|---|
| Prompter | Gemma 4 4B | ~3 GB | Fast, precise at reformulating — the sweet spot |
| Prompter | Phi-4 Mini Reasoning | ~4 GB | Reasoning-tuned alternative |
| Coder | Qwen 2.5 Coder 14B | ~10 GB | Best overall local coding quality |
| Coder | Qwen 2.5 Coder 7B | ~5 GB | Good for 8 GB cards |
| Coder | *any cloud model* | 0 GB | The hybrid setup — free drafting, one paid generation |

> Pair a ~3–4 GB Prompter with the largest Coder that fits your remaining VRAM. Thinking models work out of the box.

---

## 🗂️ Repo layout

```
├── src/promptchain/        # 📦 the library (published to PyPI)
│   ├── manager.py          #    ModelManager: N-model registry, policies, eviction, groups
│   ├── lifecycle.py        #    load / unload / loaded_models (LM Studio instance-aware)
│   ├── streaming.py        #    unified streaming, ThinkTagFilter, ToolCallFilter
│   ├── mcp_server.py       #    promptchain-mcp: agent tools over MCP (stdio)
│   └── ...                 #    backends, discovery, endpoint, endpoints_file, costs, errors
├── app.py + ui/ + core/    # 🔗 the Streamlit app (uses the library)
├── presets/presets.json    #    46 built-in system-prompt presets
├── examples/               #    agent MCP setup guide, ModelManager demo
└── tests/                  #    220+ tests (pytest)
```

## 📄 License

MIT — see [LICENSE](LICENSE).

---

Built for tinkerers who run LLMs at home — local-first, cloud when you want it, **no telemetry**.

⭐ Star it if it's useful · 🐛 [Issues](https://github.com/atharva557/Prompt-Chaining/issues) welcome · 🔌 PRs for new backends and presets welcome
