"""MCP server tests — an in-process MCP client session drives the FastMCP
server end-to-end (list tools, call each tool) with the HTTP layer mocked."""

import asyncio
import json
import unittest
from unittest import mock

from mcp.shared.memory import create_connected_server_and_client_session

from promptchain import Endpoint, ModelManager
from promptchain.mcp_server import build_server
from promptchain.streaming import StreamingResponse


def _call(server, tool: str, args: dict | None = None):
    """Run one tool call through an in-memory client session."""
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(tool, args or {})
    return asyncio.run(go())


def _payload(result) -> dict:
    assert not result.isError, result.content
    if result.structuredContent:
        data = result.structuredContent
        return data.get("result", data)
    return json.loads(result.content[0].text)


def _make_server():
    manager = ModelManager(policy="auto", max_resident=1)
    manager.register("prompter", Endpoint("lmstudio", "gemma-4-4b"))
    manager.register("coder", Endpoint("ollama", "qwen3-coder:30b"))
    return build_server(manager=manager), manager


class MCPTestCase(unittest.TestCase):
    def setUp(self):
        self.load_mock = mock.patch(
            "promptchain.lifecycle.load_model", return_value=True
        ).start()
        self.unload_mock = mock.patch(
            "promptchain.lifecycle.unload_model", return_value=True
        ).start()
        self.loaded_mock = mock.patch(
            "promptchain.lifecycle.loaded_models", return_value=[]
        ).start()
        self.addCleanup(mock.patch.stopall)
        self.server, self.manager = _make_server()


class TestToolInventory(MCPTestCase):
    def test_expected_tools_exposed(self):
        async def go():
            async with create_connected_server_and_client_session(self.server) as session:
                return {t.name for t in (await session.list_tools()).tools}
        names = asyncio.run(go())
        self.assertEqual(names, {
            "ps", "load_model", "unload_model", "swap",
            "unload_all", "list_models", "health", "generate",
        })


class TestManagementTools(MCPTestCase):
    def test_ps_reports_servers_and_configured_models(self):
        self.loaded_mock.return_value = [
            {"model": "qwen3-coder:30b", "vram_bytes": 18 * 2**30,
             "context_length": 40960},
        ]
        data = _payload(_call(self.server, "ps"))
        self.assertIn("ollama @ http://localhost:11434", data["servers"])
        entry = data["servers"]["ollama @ http://localhost:11434"][0]
        self.assertEqual(entry["model"], "qwen3-coder:30b")
        self.assertEqual(entry["vram_mib"], 18 * 1024)
        self.assertEqual(
            sorted(data["configured_models"]), ["coder", "prompter"]
        )
        # refresh_residency reconciled belief with the mocked server truth
        self.assertTrue(data["configured_models"]["coder"]["resident"])

    def test_load_then_swap_flow(self):
        data = _payload(_call(self.server, "load_model", {"name": "prompter"}))
        self.assertTrue(data["loaded"])
        self.assertEqual(data["resident"], ["prompter"])
        data = _payload(_call(self.server, "swap",
                              {"unload": "prompter", "load": "coder"}))
        self.assertTrue(data["load_ok"])
        self.assertEqual(data["resident"], ["coder"])
        data = _payload(_call(self.server, "unload_all"))
        self.assertEqual(data["resident"], [])

    def test_unload_model(self):
        _call(self.server, "load_model", {"name": "coder"})
        data = _payload(_call(self.server, "unload_model", {"name": "coder"}))
        self.assertTrue(data["unload_attempted"])
        self.assertEqual(data["resident"], [])

    def test_unknown_name_is_a_tool_error(self):
        result = _call(self.server, "load_model", {"name": "ghost"})
        self.assertTrue(result.isError)

    def test_list_models(self):
        with mock.patch(
            "promptchain.discovery.get_models",
            return_value=(["gemma-4-4b", "qwen3-coder:30b"], ""),
        ):
            data = _payload(_call(self.server, "list_models"))
        self.assertEqual(
            data["lmstudio @ http://localhost:1234"]["models"],
            ["gemma-4-4b", "qwen3-coder:30b"],
        )

    def test_health(self):
        with mock.patch(
            "promptchain.discovery.test_connection",
            return_value=(True, "Connected successfully!"),
        ):
            data = _payload(_call(self.server, "health"))
        for report in data.values():
            self.assertTrue(report["ok"])


class TestGenerateTool(MCPTestCase):
    def test_generate_returns_text_reasoning_and_usage(self):
        fake = StreamingResponse(
            iter(["hello ", "world"]),
            {"input_tokens": 4, "output_tokens": 2},
            {"text": "let me think"},
            [],
        )
        with mock.patch("promptchain.manager.stream", return_value=fake):
            data = _payload(_call(self.server, "generate",
                                  {"name": "coder", "prompt": "greet me"}))
        self.assertEqual(data["text"], "hello world")
        self.assertEqual(data["reasoning"], "let me think")
        self.assertEqual(data["usage"]["input_tokens"], 4)
        self.assertEqual(data["model"], "qwen3-coder:30b")
        # the generation loaded the model per auto policy
        self.assertEqual(self.manager.resident(), ["coder"])


if __name__ == "__main__":
    unittest.main()
