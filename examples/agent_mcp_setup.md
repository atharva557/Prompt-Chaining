# Let your agent manage your GPU: promptchain's MCP server

`promptchain-mcp` exposes local-model management over the
[Model Context Protocol](https://modelcontextprotocol.io), so an agent —
**Hermes Agent**, **Claude Code**, **Claude Desktop**, or any MCP client —
can see what's occupying your VRAM, free it, pre-warm models, and run
one-shot generations through them.

## Install

```bash
pip install "promptchain[mcp]"
```

This gives you the `promptchain-mcp` command (stdio transport).

## Configure your models: endpoints.toml

On first run the server creates `endpoints.toml` in your user config
directory (Windows: `%APPDATA%\promptchain\`, Linux:
`~/.config/promptchain/`, macOS: `~/Library/Application Support/promptchain/`).
If you run it from a folder containing a PromptChain app `config.json`, your
prompter/coder models are seeded automatically.

```toml
[manager]
policy = "auto"        # "auto" = evict others as needed; "manual" = agent drives everything
max_resident = 1       # how many local models may be loaded at once (0 = uncapped)
idle_unload = 300      # seconds of inactivity before a model is evicted (0 = never)

[models.drafter]
backend = "lmstudio"   # lmstudio | ollama | custom | openai | anthropic | gemini
base_url = "http://localhost:1234"
model = "gemma-4-4b"

[models.coder]
backend = "ollama"
base_url = "http://localhost:11434"
model = "qwen3-coder:30b"
priority = 10          # higher priority survives eviction longer
# pinned = true        # never auto-evicted
# vram_hint = "18GiB"  # for vram_budget accounting
```

API keys are **not** stored here — cloud models read `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, or `GEMINI_API_KEY` from the environment.

## Hermes Agent

Hermes Agent (Nous Research) consumes MCP servers via its config. Add
promptchain to the `mcpServers` block of your Hermes config (the same
`mcpServers` shape is used across most MCP-capable agents):

```json
{
  "mcpServers": {
    "promptchain": {
      "command": "promptchain-mcp",
      "args": []
    }
  }
}
```

If `promptchain-mcp` isn't on the PATH Hermes runs with, use the absolute
interpreter instead:

```json
{
  "mcpServers": {
    "promptchain": {
      "command": "python",
      "args": ["-m", "promptchain.mcp_server", "--config", "/path/to/endpoints.toml"]
    }
  }
}
```

Typical Hermes usage once connected: *"free the GPU before you start"* →
Hermes calls `unload_all`; *"use the local coder for this"* → Hermes calls
`load_model("coder")` then `generate`.

Tip: if you run Hermes Agent itself on a local model (Ollama/LM Studio), keep
that model out of `endpoints.toml` or set `pinned = true` on it — otherwise
the agent can be told to unload the very model it is thinking with.

## Claude Code

```bash
claude mcp add promptchain -- promptchain-mcp
```

or in `.mcp.json` at your project root:

```json
{
  "mcpServers": {
    "promptchain": {
      "command": "promptchain-mcp"
    }
  }
}
```

## Claude Desktop

Add the same block to `claude_desktop_config.json` (Settings → Developer →
Edit Config).

## The tools

| Tool | What it does |
|---|---|
| `ps` | What's loaded right now, per server, with VRAM (MiB) where reported, plus the state of every configured model |
| `load_model(name)` | Pre-warm a configured model (evicting others per policy); blocks until up |
| `unload_model(name)` | Free a model's VRAM |
| `swap(unload, load)` | Ordered unload→load in one step — for GPUs that fit only one model |
| `unload_all()` | Free the whole GPU |
| `list_models()` | Every model *installed* on each configured server |
| `health(timeout_seconds=0)` | Check each server; with a timeout, poll until it comes up |
| `generate(name, prompt, …)` | One-shot generation through a configured model; hidden `<think>` reasoning is stripped and returned separately |

Models are addressed by their **configured names** (`drafter`, `coder`, …),
never raw model ids — `ps` shows the mapping.

## Hermes-format tool calling (library side)

Independent of the MCP server: if you build your *own* agent loop on local
models, `promptchain.stream(..., tools=[...])` forwards OpenAI-style tool
definitions and surfaces calls on `StreamingResponse.tool_calls` — both for
servers that parse tool calls natively (Ollama; vLLM with
`--tool-call-parser hermes`; llama.cpp with `--jinja`) and for plain servers
that leak raw Hermes `<tool_call>{"name": …}</tool_call>` tags into the text
stream (extracted by `promptchain.ToolCallFilter`).
