import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import (ModelAPIError, check_model_api, load_local_env, main, main_async,
                   prompt_provider, resolve_provider, run_turn, tool_reply)


class FakeSession:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text='{"status":"ok","revision":"32.5.1"}')])


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_diagnostic_never_starts_mcp_and_bounds_output(self):
        path = Path(__file__).resolve().parents[1] / "providers.example.json"
        requests = []
        def mock(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": "API_CONNECTION_OK"}}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(mock))
        args = SimpleNamespace(config=path, env_file=None, interactive_setup=False,
                               model="gpt-5.4-mini", provider="openai",
                               check_config=False, check_api=True)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-only"}, clear=True), \
             patch("agent.load_local_env"), \
             patch("agent.httpx.AsyncClient", return_value=client), \
             patch("agent.stdio_client", side_effect=AssertionError("MCP must not start")), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            await main_async(args)
            self.assertIn("API_CHECK_OK", output.getvalue())
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["model"], "gpt-5.4-mini")
        self.assertEqual(requests[0]["max_completion_tokens"], 32)
        self.assertNotIn("tools", requests[0])
        self.assertFalse(requests[0]["store"])

    async def test_api_diagnostic_401_returns_safe_server_code(self):
        def mock(request):
            return httpx.Response(401, json={"error": {"code": "invalid_api_key", "message": "echoed SECRET"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
            with self.assertRaises(ModelAPIError) as ctx:
                await check_model_api(client, "https://example.invalid/v1", "test", {}, "openai")
        self.assertEqual(ctx.exception.api_code, "invalid_api_key")
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_unknown_error_code_is_not_echoed(self):
        error = ModelAPIError(httpx.Response(404, json={"error": {"code": "sk-SECRET", "message": "SECRET"}}))
        self.assertIsNone(error.api_code)
        self.assertNotIn("SECRET", str(error))

    def test_quota_and_rate_limit_have_different_explanations(self):
        quota = ModelAPIError(httpx.Response(429, json={"error": {"code": "insufficient_quota"}}))
        rate = ModelAPIError(httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}}))
        self.assertNotEqual(str(quota), str(rate))
        self.assertIn("额度", str(quota))

    def test_model_override_and_invalid_key_input(self):
        path = Path(__file__).resolve().parents[1] / "providers.example.json"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-only"}, clear=True):
            _, model, _, _ = resolve_provider(path, "openai", "gpt-5.4-mini")
            self.assertEqual(model, "gpt-5.4-mini")
        for key in ("project-id", "sk-part...masked", "sk-part\x16invalid", "sk-two words"):
            with self.subTest(key_kind="malformed"), patch.dict(os.environ, {"OPENAI_API_KEY": key}, clear=True):
                with self.assertRaises(ValueError) as ctx:
                    resolve_provider(path, "openai", "gpt-5.4-mini")
                self.assertNotIn(key, str(ctx.exception))

    def test_diagnostic_interactive_input_replaces_cached_key_in_process_only(self):
        path = Path(__file__).resolve().parents[1] / "providers.example.json"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-old"}, clear=True), \
             patch("agent.input", side_effect=AssertionError("Model is fixed")), \
             patch("agent.getpass", return_value="sk-new") as hidden_input:
            prompt_provider(path, "openai", "gpt-5.4-mini", force_key=True)
            hidden_input.assert_called_once()
            self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-new")

    def test_local_env_preserves_process_and_literal_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text('OPENAI_MODEL=file-model\nOPENAI_API_KEY="literal-${HOME}"\n', encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_MODEL": "process-model"}, clear=True):
                load_local_env(path)
                self.assertEqual(os.environ["OPENAI_MODEL"], "process-model")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "literal-${HOME}")

    def test_configured_provider_does_not_prompt_for_secret(self):
        path = Path(__file__).resolve().parents[1] / "providers.example.json"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only", "OPENAI_MODEL": "test-model"}, clear=True):
            with patch("agent.input", side_effect=AssertionError("Unexpected input")), \
                 patch("agent.getpass", side_effect=AssertionError("Unexpected credential prompt")):
                prompt_provider(path, "openai")

    async def test_model_tool_result_second_model_round(self):
        session = FakeSession()
        requests = []
        def mock(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                message = {"role": "assistant", "content": None, "reasoning_content": "provider field",
                    "tool_calls": [{"id": "call_1", "type": "function", "function": {
                        "name": "solidworks_connect", "arguments": '{"params":{}}'}}]}
            else:
                self.assertEqual(body["messages"][-1]["role"], "tool")
                self.assertEqual(body["messages"][-2]["reasoning_content"], "provider field")
                message = {"role": "assistant", "content": "Connected"}
            return httpx.Response(200, json={"choices": [{"message": message}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
            result = await run_turn(session, client, "https://example.invalid/v1", "test", {},
                [{"role": "user", "content": "Connect"}],
                [{"type": "function", "function": {"name": "solidworks_connect"}}], 3)
        self.assertEqual(result, "Connected")
        self.assertEqual(session.calls, [("solidworks_connect", {"params": {}})])

    async def test_unknown_tool_never_executes(self):
        session = FakeSession()
        result = await tool_reply(session, {"id": "x", "function": {"name": "shell", "arguments": "{}"}}, set())
        self.assertTrue(json.loads(result["content"])["isError"])
        self.assertEqual(session.calls, [])

    async def test_invalid_json_never_executes(self):
        session = FakeSession()
        result = await tool_reply(session, {"id": "x", "function": {"name": "cad", "arguments": "not json"}}, {"cad"})
        self.assertTrue(json.loads(result["content"])["isError"])
        self.assertEqual(session.calls, [])

    async def test_http_error_does_not_echo_key(self):
        def mock(request):
            return httpx.Response(401, text="echoed SECRET")
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as ctx:
                await run_turn(FakeSession(), client, "https://example.invalid/v1", "x", {}, [], [], 1)
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_provider_environment_and_missing_key(self):
        path = Path(__file__).resolve().parents[1] / "providers.example.json"
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-secret"}, clear=True):
            base, model, key, _ = resolve_provider(path, "deepseek")
            self.assertEqual(base, "https://api.deepseek.com")
            self.assertEqual(key, "test-secret")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                resolve_provider(path, "deepseek")


class CliErrorTests(unittest.TestCase):
    def test_nested_mcp_exception_group_shows_api_error_without_traceback(self):
        api_error = ModelAPIError(httpx.Response(401, json={"error": {"code": "invalid_api_key", "message": "SECRET"}}))
        nested = ExceptionGroup("MCP task group", [ExceptionGroup("session", [api_error])])
        with patch("sys.argv", ["agent.py", "--check-api"]), \
             patch("agent.main_async", new=AsyncMock(side_effect=nested)), \
             patch("sys.stderr", new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as ctx:
                main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("HTTP 401", output.getvalue())
        self.assertIn("invalid_api_key", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        self.assertNotIn("SECRET", output.getvalue())


if __name__ == "__main__":
    unittest.main()
