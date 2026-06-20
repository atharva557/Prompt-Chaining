<div align="center">

# 🔗 PromptChain

**Two models, one pipeline, zero manual model-swapping.**

Chain a **Prompter** that refines your idea with a **Coder** that writes the code — local, cloud, or a hybrid of both.

[![CI](https://github.com/atharva557/Prompt-Chaining/actions/workflows/ci.yml/badge.svg)](https://github.com/atharva557/Prompt-Chaining/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.35%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Local-first, cloud optional](https://img.shields.io/badge/local--first-cloud_optional-blueviolet)](#)

</div>

---

Running local LLMs on consumer hardware (8–16 GB VRAM) usually means you can only load one model at a time. PromptChain solves the tedious workflow of manually switching models and copy-pasting outputs between them. It chains a small **Prompter** model and a larger **Coder** model into a single, seamless pipeline — automatically swapping VRAM between models so you never have to.

Each role has its own backend, so you can keep the Prompter local and point the Coder at a frontier cloud model (OpenAI, Claude, or Gemini) — **frontier code quality on a budget GPU, paying only for the one generation that matters.**

> ⭐ **If PromptChain saves you some VRAM-juggling, a star helps other tinkerers find it.**

## 🔄 How It Works

```
┌──────────────────────────────────────────────────────┐
│  1. You type a rough idea                            │
│     "make a snake game in React"                     │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│  2. Prompter Model (small / fast)                    │
│     e.g. Phi-4 Mini · ~4 GB VRAM                     │
│     Rewrites your idea into a detailed prompt        │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│  3. You review, edit, or retry the generated prompt  │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│  4. VRAM Swap                                        │
│     Prompter unloads → Coder loads                   │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│  5. Coder Model (larger / coding-optimized)          │
│     e.g. Qwen 2.5 Coder 14B · ~10 GB VRAM           │
│     Generates production-ready code                  │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│  6. Code streams to screen → saved to file           │
└──────────────────────────────────────────────────────┘
```

The free local **review gate** at step 3 is the trick behind the hybrid mode: you fix the prompt on a local model for free, so the one expensive cloud generation lands right more often and you re-roll far less.

## 🎯 Features

|    | Feature                          | Details                                                                                                                                 |
| --- | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 🔗  | **Two-model pipeline**           | Prompter → review / edit → Coder                                                                                                        |
| 📡  | **Real-time streaming**          | Token-by-token output via SSE, with tokens/sec stats                                                                                    |
| 🧠  | **VRAM-aware model swapping**    | Automatically unloads the Prompter before loading the Coder                                                                             |
| 🔌  | **Per-role backends**            | Mix local and cloud: LM Studio, Ollama, any OpenAI-compatible server, plus OpenAI, Claude, and Gemini — chosen separately for each role |
| 💸  | **Local Prompter + cloud Coder** | Refine prompts for free on a local model, then send one clean prompt to a frontier cloud Coder — fewer wasted paid generations          |
| 🔍  | **Auto model detection**         | Installed models are detected and listed automatically                                                                                  |
| 🕘  | **Run history**                  | Past runs persist across restarts; reopen or delete them from the sidebar                                                               |
| ♻️ | **Refine in place**              | Send a follow-up instruction ("make the board bigger") to edit the code without regenerating from scratch                               |
| 💬  | **Direct chats**                 | ChatGPT-style pages for just the Prompter or just the Coder when you don't need the full pipeline                                       |
| 📋  | **37 built-in presets**          | Across General, Web Development, Data & Scripts, Games & Graphics, Systems & CLI, and Testing                                            |
| ✏️ | **Presets manager**              | Browse and edit every preset; edits to built-ins are saved as overrides (reset to default anytime), plus create/delete your own         |
| 🗂️ | **Smart file output**            | Auto language detection, suggested filenames, timestamped saves, browser download                                                       |
| 🌙  | **Polished dark UI**             | Clean Tokyo Night theme; tokens/sec for local runs and exact tokens + a cost estimate for cloud                                         |

## 📦 Requirements

- **Python 3.10+**
- A model source for each role — any mix of:
  - **Local:** LM Studio, Ollama, or any OpenAI-compatible server (llama.cpp, llama-swap, vLLM, Jan…)
  - **Cloud:** OpenAI, Anthropic (Claude), or Google Gemini — bring your own API key
- The Anthropic backend needs the `anthropic` package (in `requirements.txt`; lazily imported, so local-only setups can skip it)

## 🚀 Quick Start

You only need **Python 3.10+** installed ([python.org](https://www.python.org/downloads/) — on Windows, tick *"Add Python to PATH"*). After that, pick either option.

### Option A — Double-click (no terminal)

1. Get the project: **Code → Download ZIP** and unzip it (or clone it).
2. Double-click the launcher for your OS:

   | OS | File |
   |---|---|
   | Windows | `run.bat` |
   | macOS | `run.command` *(first time: right-click → Open if blocked)* |
   | Linux | `run.sh` |

The first launch sets everything up automatically — a self-contained environment and dependencies — then opens PromptChain in your browser. Later launches start straight away. Keep the launcher window open while you use the app; close it to quit.

### Option B — Terminal

```bash
# Clone the repository
git clone https://github.com/atharva557/Prompt-Chaining.git
cd Prompt-Chaining

# Install dependencies
pip install -r requirements.txt

# Launch the app
streamlit run app.py
```

On first launch the **Settings** page opens automatically — your installed models are detected and listed, so you just pick two and save.

To run the test suite:

```bash
pip install -r requirements-dev.txt
pytest
```

## ⚙️ Configuration

Each role (Prompter / Coder) is configured independently in **Settings**:

| Setting                | Default       | Notes                                                                                                                          |
| ---------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Backend (per role)     | LM Studio     | LM Studio, Ollama, Custom (OpenAI-compatible), OpenAI, Anthropic, or Gemini — chosen separately for the Prompter and the Coder |
| Base URL (per role)    | per-backend   | Editable for local/custom backends; fixed for cloud providers                                                                  |
| Model (per role)       | —             | Auto-detected from the server, or entered manually                                                                             |
| Temperature (per role) | 0.3 / 0.1     | Lower = more deterministic                                                                                                     |
| Max Tokens (per role)  | 1024 / 4096   | Max output length                                                                                                              |
| Output Folder          | `./output`    | Where generated code files are saved                                                                                           |
| Auto-unload coder      | 5 min         | Free local VRAM after the coder sits idle this long (`0` = never; local backends only)                                         |

**API keys** for the cloud backends are read from environment variables first — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — and fall back to keys entered in Settings. Settings (including any typed-in keys) persist in `config.json` (git-ignored).

> **Tip — the local-Prompter + cloud-Coder hybrid:** it doesn't lower paid input tokens (the refined prompt is longer), but it cuts the *number* of paid generations — the free local review gate means the one expensive cloud generation lands right more often, so you re-roll far less.

## 🤖 Recommended Models

### Prompter (small / fast)

| Model                | VRAM  | Notes                              |
| -------------------- | ----- | ---------------------------------- |
| Phi-4 Mini Reasoning | ~4 GB | Fast, great at reformulating tasks |
| Qwen 2.5 3B          | ~3 GB | Lightweight alternative            |

### Coder (larger / code-focused)

| Model                  | VRAM   | Notes                           |
| ---------------------- | ------ | ------------------------------- |
| Qwen 2.5 Coder 14B     | ~10 GB | Best overall coding quality     |
| DeepSeek Coder V2 Lite | ~9 GB  | Strong alternative              |
| Qwen 2.5 Coder 7B      | ~5 GB  | Good choice for 8 GB VRAM cards |

> **Tip:** Pair a ~3–4 GB Prompter with the largest Coder that fits in your remaining VRAM for the best results.

## 🗂️ Project Structure

```
promptchain/
├── app.py                   # Main entry point & pipeline orchestration
├── run.py                   # One-click launcher (sets up env, starts server, opens browser)
├── run.bat / run.command / run.sh   # Double-click launchers (Windows / macOS / Linux)
├── core/
│   ├── api.py               # Backend API calls, model unload, cost estimates
│   ├── config.py            # Config & preset management
│   ├── history.py           # Persistent run history (history.json)
│   └── streaming.py         # Real-time SSE / SDK token streaming
├── ui/
│   ├── styles.py            # Dark theme CSS + UI components
│   ├── landing.py           # Landing page
│   ├── settings.py          # Settings page (auto model detection)
│   ├── task_input.py        # Task input + preset selector
│   ├── prompt_review.py     # Prompt review / edit step
│   ├── code_output.py       # Side-by-side prompt/code, save & download
│   ├── chat.py              # Direct Prompter / Coder chat pages
│   └── presets.py           # Presets manager
├── presets/
│   └── presets.json         # 37 built-in system prompt presets
├── tests/                   # Pytest suite for the core helpers
├── .streamlit/
│   └── config.toml          # Streamlit theme configuration
├── requirements.txt         # Runtime deps (+ requirements-dev.txt for tests)
└── .gitignore
```

## 🛠️ Tech Stack

| Layer            | Technology                                                           |
| ---------------- | -------------------------------------------------------------------- |
| UI Framework     | [Streamlit](https://streamlit.io/) ≥ 1.35                            |
| HTTP & Streaming | [requests](https://docs.python-requests.org/) (SSE via `iter_lines`) |
| Cloud SDK        | [anthropic](https://pypi.org/project/anthropic/) (Claude backend)    |
| File Management  | Python `pathlib`                                                     |
| Config Storage   | JSON (`config.json`)                                                  |

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

Built for tinkerers who run LLMs at home — local-first, with cloud models when you want them. **No telemetry.**

⭐ Star it if it's useful · 🐛 [Open an issue](https://github.com/atharva557/Prompt-Chaining/issues) if something breaks · 🔌 PRs for new backends and presets welcome
