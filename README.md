<div align="center">

# ⚡ PromptChain

**Chain two local LLMs together: a Prompter that refines your idea, and a Coder that writes the code.**

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/streamlit-1.35%2B-FF4B4B?logo=streamlit&logoColor=white)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![Local First](https://img.shields.io/badge/local--first-no_cloud_required-blueviolet)

</div>

---

Running local LLMs on consumer hardware (8–16 GB VRAM) usually means you can only load one model at a time. PromptChain solves the tedious workflow of manually switching models and copy-pasting outputs between them. It chains a small **Prompter** model and a larger **Coder** model into a single, seamless pipeline — automatically swapping VRAM between models so you never have to.

<br>

## 🎯 Features

| | Feature | Details |
|---|---|---|
| 🔗 | **Two-model pipeline** | Prompter → review / edit → Coder |
| 📡 | **Real-time streaming** | Token-by-token output via SSE, with tokens/sec stats |
| 🧠 | **VRAM-aware model swapping** | Automatically unloads the Prompter before loading the Coder |
| 🔌 | **Per-role backends** | Mix local and cloud: LM Studio, Ollama, any OpenAI-compatible server, plus OpenAI, Claude, and Gemini — chosen separately for each role |
| 💸 | **Local Prompter + cloud Coder** | Refine prompts for free on a local model, then send one clean prompt to a frontier cloud Coder — fewer wasted paid generations |
| 🔍 | **Auto model detection** | Installed models are detected and listed automatically |
| 🕘 | **Run history** | Past runs persist across restarts; reopen or delete them from the sidebar |
| ⚡ | **Side-by-side output** | Edit the prompt next to the generated code and regenerate in place |
| 📋 | **25 built-in presets** | Across General, Web Dev, Data & Scripts, Games & Graphics, and Systems & CLI |
| ✏️ | **Custom preset saving** | Save your own system prompts for either role |
| 🗂️ | **Smart file output** | Auto language detection, suggested filenames, timestamped saves, browser download |
| 🌙 | **Minimal dark theme** | Clean, ChatGPT/Claude-inspired interface with a warm accent |

<br>

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

<br>

## 📦 Requirements

- **Python 3.10+**
- A model source for each role — any mix of:
  - **Local:** LM Studio, Ollama, or any OpenAI-compatible server (llama.cpp, llama-swap, vLLM, Jan…)
  - **Cloud:** OpenAI, Anthropic (Claude), or Google Gemini — bring your own API key
- The Anthropic backend needs the `anthropic` package (in `requirements.txt`; lazily imported, so local-only setups can skip it)

<br>

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/promptchain.git
cd promptchain

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

<br>

## ⚙️ Configuration

Each role (Prompter / Coder) is configured independently in **Settings**:

| Setting | Default | Notes |
|---|---|---|
| Backend (per role) | LM Studio | LM Studio, Ollama, Custom (OpenAI-compatible), OpenAI, Anthropic, or Gemini — chosen separately for the Prompter and the Coder |
| Base URL (per role) | per-backend | Editable for local/custom backends; fixed for cloud providers |
| Model (per role) | — | Auto-detected from the server, or entered manually |
| Temperature (per role) | 0.3 / 0.1 | Lower = more deterministic |
| Max Tokens (per role) | 1 024 / 4 096 | Max output length |
| Output Folder | `./output` | Where generated code files are saved |

**API keys** for the cloud backends are read from environment variables first —
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — and fall back to keys
entered in Settings. Settings (including any typed-in keys) persist in
`config.json` (git-ignored).

> **Tip — the local-Prompter + cloud-Coder hybrid:** it doesn't lower paid input
> tokens (the refined prompt is longer), but it cuts the *number* of paid
> generations — the free local review gate means the one expensive cloud
> generation lands right more often, so you re-roll far less.

<br>

## 🗂️ Project Structure

```
promptchain/
├── app.py                   # Main entry point & pipeline orchestration
├── core/
│   ├── api.py               # LM Studio / Ollama API calls + model unload
│   ├── config.py            # Config & preset management
│   ├── history.py           # Persistent run history (history.json)
│   └── streaming.py         # Real-time SSE token streaming
├── ui/
│   ├── styles.py            # Minimal dark theme CSS + UI components
│   ├── settings.py          # Settings page (auto model detection)
│   ├── task_input.py        # Task input + preset selector
│   ├── prompt_review.py     # Prompt review / edit step
│   └── code_output.py       # Side-by-side prompt/code, save & download
├── presets/
│   └── presets.json         # 25 built-in system prompt presets
├── tests/                   # Pytest suite for the core helpers
├── .streamlit/
│   └── config.toml          # Streamlit theme configuration
├── requirements.txt
└── .gitignore
```

<br>

## 🤖 Recommended Models

### Prompter (small / fast)

| Model | VRAM | Notes |
|---|---|---|
| Phi-4 Mini Reasoning | ~4 GB | Fast, great at reformulating tasks |
| Qwen 2.5 3B | ~3 GB | Lightweight alternative |

### Coder (larger / code-focused)

| Model | VRAM | Notes |
|---|---|---|
| Qwen 2.5 Coder 14B | ~10 GB | Best overall coding quality |
| DeepSeek Coder V2 Lite | ~9 GB | Strong alternative |
| Qwen 2.5 Coder 7B | ~5 GB | Good choice for 8 GB VRAM cards |

> **Tip:** Pair a ~3–4 GB Prompter with the largest Coder that fits in your remaining VRAM for the best results.

<br>

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| UI Framework | [Streamlit](https://streamlit.io/) ≥ 1.35 |
| HTTP & Streaming | [requests](https://docs.python-requests.org/) (SSE via `iter_lines`) |
| File Management | Python `pathlib` |
| Config Storage | JSON (`config.json`) |

<br>

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

<div align="center">
<sub>Built for tinkerers who run LLMs at home. No cloud, no API keys, no telemetry.</sub>
</div>
