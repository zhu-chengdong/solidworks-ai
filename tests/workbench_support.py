from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import httpx2
from openai import AsyncOpenAI
from agents import OpenAIResponsesModel, OpenAIChatCompletionsModel

from workbench.settings import SettingsStore


class MemoryVault:
    def __init__(self):
        self.values = {}
    def put(self, provider, base_url, key):
        self.values[(provider, base_url)] = key
    def get(self, provider, base_url):
        return self.values.get((provider, base_url), "")
    def has(self, provider, base_url):
        return bool(self.get(provider, base_url))
    def remove(self, provider, base_url):
        self.values.pop((provider, base_url), None)


def configured_store(root):
    store = SettingsStore(Path(root) / "settings", MemoryVault())
    store.save(store.read(), {"openai": "sk-test-placeholder-not-real"})
    return store


class FakeMCP:
    def __init__(self):
        self.calls = []
        self.active = None
        self.fail_create = False
    async def list_tools(self):
        simple = {"type": "object", "properties": {"params": {"type": "object"}}, "required": ["params"]}
        names = ["solidworks_health_check", "solidworks_connect", "solidworks_mcp_info",
                 "solidworks_create_basic_part", "solidworks_mass_properties", "solidworks_bounding_box"]
        return SimpleNamespace(tools=[SimpleNamespace(name=name, description=name, inputSchema=simple) for name in names])
    async def call_tool(self, name, args):
        self.calls.append((name, args))
        data = {"status": "ok"}
        error = False
        if name == "solidworks_connect":
            data.update(revision="32.0.1", active_document=self.active)
        if name == "solidworks_create_basic_part":
            if self.fail_create:
                data = {"status": "failed", "error": "test failure"}
                error = True
            else:
                self.active = {"title": "test-part", "path": args["params"]["output_path"], "type": 1}
                # Deliberately create no CAD file: missing-file acceptance must fail.
                data.update(document=self.active, saved=True, feature_created=True, rebuild_ok=True)
        return SimpleNamespace(isError=error, structuredContent=None,
            content=[SimpleNamespace(type="text", text=json.dumps(data))])
    @asynccontextmanager
    async def session(self):
        yield self


class ScriptedAPI:
    def __init__(self, action="inspect", clarify=False, outside=None, api_error=None):
        self.requests = []
        self.action, self.clarify, self.outside, self.api_error = action, clarify, outside, api_error

    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        if self.api_error:
            return httpx2.Response(self.api_error, json={"error": {"code": "invalid_api_key", "message": "echo sk-test-placeholder-not-real"}})
        if request.url.path.endswith("/chat/completions"):
            if body["model"] == "deepseek-v4-pro":
                text = json.dumps({"summary": "检查连接", "action": "inspect", "needs_clarification": False,
                    "supported": True, "questions": [], "steps": ["读取实际连接"], "checks": ["核对版本"]})
                message = {"role": "assistant", "content": text}
                finish = "stop"
            elif body.get("tools") and not any(item.get("role") == "tool" for item in body["messages"]):
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "chat_call_test", "type": "function",
                    "function": {"name": "solidworks_connect", "arguments": '{"params":{}}'}}]}
                finish = "tool_calls"
            else:
                message = {"role": "assistant", "content": "已读取实际连接。"}
                finish = "stop"
            return httpx2.Response(200, json={"id": "chatcmpl_test", "object": "chat.completion", "created": 1700000000,
                "model": body["model"], "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40}})
        schema = body.get("text", {}).get("format", {}).get("schema", {})
        properties = schema.get("properties", {})
        if "needs_clarification" in properties:
            text = json.dumps({"summary": "检查连接" if self.action == "inspect" else "创建10毫米立方体",
                "action": self.action, "needs_clarification": self.clarify, "supported": True,
                "questions": ["请提供长、宽、高。"] if self.clarify else [],
                "steps": ["连接并读取实际结果"], "checks": ["核对实际结果"]}, ensure_ascii=False)
            output = self.message(text)
        elif "passed" in properties:
            output = self.message(json.dumps({"passed": True, "summary": "模拟复核", "issues": []}))
        elif body.get("tools") and not any(item.get("type") == "function_call_output" for item in body.get("input", []) if isinstance(item, dict)):
            name = "solidworks_connect" if self.action == "inspect" else "solidworks_create_basic_part"
            args = {"params": {}}
            if self.action != "inspect":
                args["params"] = {"shape": "box", "width_mm": 10, "height_mm": 10, "depth_mm": 10}
                if self.outside:
                    args["params"]["output_path"] = str(self.outside)
            output = [{"id": "fc_test", "type": "function_call", "call_id": "call_test", "name": name,
                       "arguments": json.dumps(args), "status": "completed"}]
        else:
            output = self.message("模拟执行结果：已读取实际工具输出。")
        return httpx2.Response(200, json={"id": "resp_test_" + str(len(self.requests)), "object": "response",
            "created_at": 1700000000, "model": body["model"], "status": "completed", "output": output,
            "usage": {"input_tokens": 20, "output_tokens": 20, "total_tokens": 40}})

    @staticmethod
    def message(text):
        return [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                 "content": [{"type": "output_text", "text": text, "annotations": []}]}]

    @asynccontextmanager
    async def model(self, profile):
        async with AsyncOpenAI(api_key=profile["key"], max_retries=0,
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle))) as client:
            cls = OpenAIResponsesModel if profile["api_style"] == "responses" else OpenAIChatCompletionsModel
            yield cls(profile["model"], client)
