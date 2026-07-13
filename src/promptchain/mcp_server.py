"""MCP server — lets agents manage your local models.

Exposes the ModelManager over the Model Context Protocol (stdio), so any MCP
client — Hermes Agent, Claude Code, Claude Desktop, … — can see what is
occupying the GPU, free VRAM before heavy work, pre-warm a model it is about
to call, or run a one-shot generation through a managed model.

Endpoints come from endpoints.toml (see promptchain.endpoints_file); the file
is created on first run, seeded from the PromptChain app's config.json when
one is present in the working directory.

Run it:
    promptchain-mcp                 # console script
    python -m promptchain.mcp_server --config /path/to/endpoints.toml

Requires the `mcp` extra:  pip install "promptchain[mcp]"
"""

import argparse
from pathlib import Path

from . import discovery, lifecycle
from .endpoints_file import build_manager, default_config_path, ensure_config
from .manager import ModelManager

_INSTRUCTIONS = """\
promptchain manages which LLM models occupy the local GPU's VRAM across
LM Studio / Ollama / OpenAI-compatible servers. Call `ps` to see what is
loaded right now, `load_model` / `unload_model` / `swap` to change it,
`list_models` to see what is installed, `health` to check the servers, and
`generate` to run a prompt through one of the configured models. Models are
addressed by their configured names (shown by `ps`), not raw model ids."""


def _mib(size_bytes) -> int | None:
    return round(size_bytes / (1024 * 1024)) if size_bytes else None


def build_server(manager: ModelManager | None = None,
                 config_path: Path | None = None):
    """Construct the FastMCP server around a ModelManager (built from
    endpoints.toml when not supplied). Import of the SDK is deferred so the
    core library never needs the `mcp` extra."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised via CLI usage
        raise SystemExit(
            "The MCP server needs the 'mcp' package. "
            "Install it with: pip install \"promptchain[mcp]\""
        ) from exc

    mgr = manager if manager is not None else build_manager(config_path)
    server = FastMCP("promptchain", instructions=_INSTRUCTIONS)

    def _endpoint_servers() -> dict[tuple[str, str], list[str]]:
        """Distinct managed (base_url, backend) pairs → configured names."""
        servers: dict[tuple[str, str], list[str]] = {}
        for name in mgr.names():
            endpoint = mgr.endpoint(name)
            key = (endpoint.base_url, endpoint.backend)
            servers.setdefault(key, []).append(name)
        return servers

    @server.tool()
    def ps() -> dict:
        """What is loaded on the GPU right now: per-server resident models
        (with VRAM when the server reports it) plus the state of every
        configured model. Call this before load/unload/swap decisions."""
        mgr.refresh_residency()
        servers = {}
        for (base_url, backend), _names in _endpoint_servers().items():
            if backend not in ("lmstudio", "ollama"):
                continue
            entries = lifecycle.loaded_models(base_url, backend)
            servers[f"{backend} @ {base_url}"] = [
                {
                    "model": entry["model"],
                    "vram_mib": _mib(entry.get("vram_bytes")),
                    "context_length": entry.get("context_length"),
                }
                for entry in entries
            ]
        configured = {}
        for name, stats in mgr.stats().items():
            configured[name] = {
                "backend": stats["backend"],
                "model": stats["model"],
                "resident": stats["resident"],
                "pinned": stats["pinned"],
                "priority": stats["priority"],
                "requests": stats["requests"],
                "loads": stats["loads"],
                "unloads": stats["unloads"],
            }
        return {"servers": servers, "configured_models": configured}

    @server.tool()
    def load_model(name: str) -> dict:
        """Load (pre-warm) a configured model into VRAM. Under the 'auto'
        policy other models are evicted first as needed; blocks until the
        server reports the model up."""
        ok = mgr.load(name, wait=True)
        return {"name": name, "loaded": ok, "resident": mgr.resident()}

    @server.tool()
    def unload_model(name: str) -> dict:
        """Unload a configured model, freeing its VRAM. Best-effort: some
        servers (custom/cloud) cannot be unloaded remotely."""
        ok = mgr.unload(name)
        return {"name": name, "unload_attempted": ok, "resident": mgr.resident()}

    @server.tool()
    def swap(unload: str, load: str) -> dict:
        """Unload one configured model and load another in a single ordered
        step — the safe way to exchange models on a GPU that fits only one."""
        ok = mgr.swap(unload, load, wait=True)
        return {"unloaded": unload, "loaded": load, "load_ok": ok,
                "resident": mgr.resident()}

    @server.tool()
    def unload_all() -> dict:
        """Unload every configured model — free the whole GPU (e.g. before
        the user starts a game or a training run)."""
        mgr.unload_all()
        return {"resident": mgr.resident()}

    @server.tool()
    def list_models() -> dict:
        """All models *installed* on each configured server (not just the
        loaded ones) — useful to check whether a model id exists before
        pointing a configured name at it."""
        result = {}
        for (base_url, backend), names in _endpoint_servers().items():
            api_key = ""
            for name in names:
                api_key = mgr.endpoint(name).api_key or api_key
            models, error = discovery.get_models(base_url, backend, api_key)
            result[f"{backend} @ {base_url}"] = (
                {"models": models} if not error else {"error": error}
            )
        return result

    @server.tool()
    def health(timeout_seconds: float = 0) -> dict:
        """Check every configured server. With timeout_seconds > 0, keep
        polling until the servers come up or the deadline passes (useful
        right after starting a server)."""
        result = {}
        for (base_url, backend), names in _endpoint_servers().items():
            api_key = ""
            for name in names:
                api_key = mgr.endpoint(name).api_key or api_key
            if timeout_seconds > 0:
                ok, message = discovery.wait_until_ready(
                    base_url, backend, api_key, timeout=timeout_seconds
                )
            else:
                ok, message = discovery.test_connection(base_url, backend, api_key)
            result[f"{backend} @ {base_url}"] = {"ok": ok, "message": message}
        return result

    @server.tool()
    def generate(name: str, prompt: str, system_prompt: str = "",
                 temperature: float = 0.3, max_tokens: int = 1024) -> dict:
        """Run a one-shot generation through a configured model (loading it
        first if needed, per policy). Returns the text; hidden reasoning from
        thinking models is stripped and reported separately."""
        with mgr.use(name) as model:
            response = model.stream(
                system_prompt=system_prompt,
                user_message=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = response.consume()
        result = {"model": model.endpoint.model, "text": text}
        if response.reasoning:
            result["reasoning"] = response.reasoning
        usage = response.usage
        if usage.get("input_tokens") is not None:
            result["usage"] = usage
        return result

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="promptchain-mcp",
        description="Serve promptchain's model manager over MCP (stdio).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Path to endpoints.toml (default: {default_config_path()}; "
             "created on first run, seeded from ./config.json when present).",
    )
    args = parser.parse_args(argv)
    config_path = ensure_config(args.config)
    server = build_server(config_path=config_path)
    server.run()  # stdio transport


if __name__ == "__main__":
    main()
