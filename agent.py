"""Configurable Chat Completions tool-calling client -> local SolidWorks MCP.

MCP-capable clients may connect directly without this optional bridge.
Keys are read from environment variables or a locally confirmed env file.
"""
from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
import json
import os
from pathlib import Path
import sys
import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent
SYSTEM = """Use SolidWorks MCP native COM tools for the user's requested CAD work.
Use millimetres for dimensions. First inspect connection and active document.
Ask for missing manufacturing dimensions rather than inventing them. Preserve
existing files and save revisions to new paths. Review geometry after writing.
Do not close the user's pre-existing documents. Tool errors and review_required
are not successful delivery. Describe only actions evidenced by tool results.
Never use keyboard, mouse, window automation, arbitrary code or shell commands.
"""


class ModelAPIError(RuntimeError):
    def __init__(self, response):
        # An API error message can echo credentials. Only show known error codes.
        allowed = {"invalid_api_key", "invalid_authentication", "model_not_found",
                   "insufficient_quota", "rate_limit_exceeded", "permission_denied",
                   "organization_deactivated", "account_deactivated",
                   "organization_usage_limit_exceeded", "billing_hard_limit_reached",
                   "unsupported_country_region_territory"}
        code = None
        try:
            data = response.json()
            error = data.get("error") if isinstance(data, dict) else None
            candidate = error.get("code") if isinstance(error, dict) else None
            if isinstance(candidate, str) and candidate in allowed:
                code = candidate
        except ValueError:
            pass
        status = response.status_code
        if status == 401:
            hint = "API认证未通过。请检查完整密钥、密钥是否有效及所属项目权限。"
        elif status == 403:
            hint = "API拒绝访问。请检查组织、项目、密钥权限或服务访问限制。"
        elif status == 404:
            hint = "模型或API路径不存在，或当前项目无权访问该模型。"
        elif status == 429 and code in {"insufficient_quota", "billing_hard_limit_reached", "organization_usage_limit_exceeded"}:
            hint = "API额度或支出限额不足，请核对密钥所属组织的账单和限额。"
        elif status == 429:
            hint = "API请求受限，请根据错误代码区分速率限制和额度限制。"
        else:
            hint = "模型API拒绝了请求，请核对接口参数和服务状态。"
        self.status_code, self.api_code = status, code
        super().__init__(f"HTTP {status}" + (f"; code={code}" if code else "") + ". " + hint)


def raise_for_model_error(response):
    if response.is_error:
        raise ModelAPIError(response)


async def check_model_api(client, endpoint, model, extra, provider):
    # One small inference request; this path never starts the MCP/CAD process.
    budget_name = "max_completion_tokens" if provider == "openai" else "max_tokens"
    body = {**extra, "model": model, "stream": False, budget_name: 32,
            "messages": [{"role": "user", "content": "Reply exactly API_CONNECTION_OK."}]}
    if provider == "openai":
        body["store"] = False
    response = await client.post(endpoint + "/chat/completions", json=body)
    raise_for_model_error(response)
    try:
        content = response.json()["choices"][0]["message"].get("content")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError("API返回HTTP 200，但响应格式与Chat Completions不兼容。") from None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("API返回HTTP 200，但未返回文本；请检查模型及推理参数。")
    return "API_CHECK_OK: HTTP 200；已完成一次真实模型请求。"


def load_local_env(path: Path):
    # Do not expand ${...} expressions or overwrite the calling agent's settings.
    if path.is_file():
        load_dotenv(path, override=False, interpolate=False, encoding="utf-8-sig")


def prompt_provider(path: Path, name: str, model_override=None, force_key=False):
    config = json.loads(path.read_text(encoding="utf-8-sig"))["providers"][name]
    for field in ("base_url", "model"):
        if field == "model" and model_override:
            continue
        env_name = config.get(field + "_env")
        if env_name and not os.environ.get(env_name):
            value = input(f"Enter {field} for {name}: ").strip()
            if not value:
                raise ValueError(f"{field} is required")
            os.environ[env_name] = value
    key_env = config.get("api_key_env")
    if config.get("api_key_required", True) and key_env and (force_key or not os.environ.get(key_env)):
        value = getpass(f"Enter API key for {name} (hidden, current process only): ").strip()
        if not value:
            raise ValueError("API key is required")
        os.environ[key_env] = value


def resolve_provider(path: Path, name: str, model_override=None):
    config = json.loads(path.read_text(encoding="utf-8-sig"))["providers"][name]
    def value(field):
        env_name = config.get(field + "_env")
        return os.environ.get(env_name, "") if env_name else config.get(field, "")
    base, model = value("base_url").rstrip("/"), model_override or value("model")
    key = os.environ.get(config.get("api_key_env", ""), "")
    if not base or not model:
        raise ValueError("Set this provider's base URL/model or the named environment variables.")
    if config.get("api_key_required", True) and not key:
        raise ValueError("Missing environment variable: " + config["api_key_env"])
    url = httpx.URL(base)
    if name == "openai" and url.host == "api.openai.com" and key:
        if not key.startswith("sk-") or any(mark in key for mark in ("...", "…", "*")):
            raise ValueError("输入的不是完整OpenAI API密钥。请使用创建时复制的完整密钥，不能使用遮罩或截断值。")
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in key):
            raise ValueError("密钥中含空白或控制字符，请在本机重新粘贴完整密钥。")
    if url.scheme != "https" and not (url.scheme == "http" and url.host in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Use HTTPS for remote model endpoints; local HTTP is supported.")
    extra = config.get("extra_body", {})
    if set(extra) & {"model", "messages", "tools", "stream"}:
        raise ValueError("extra_body cannot replace model/messages/tools/stream.")
    return base, model, key, extra


def as_function(tool):
    return {"type": "function", "function": {"name": tool.name,
        "description": tool.description or tool.name, "parameters": tool.inputSchema}}


def text_result(result):
    # Do not send large CAD binary/base64 blobs to a language model.
    parts = [item.text for item in result.content if item.type == "text"]
    if any(item.type != "text" for item in result.content):
        parts.append("Binary/preview content returned locally; inspect using the MCP client.")
    return json.dumps({"isError": result.isError, "content": parts}, ensure_ascii=False)


async def tool_reply(session, call, allowed):
    name = call.get("function", {}).get("name", "")
    try:
        if name not in allowed:
            raise ValueError("Unknown or unavailable MCP tool: " + name)
        args = json.loads(call["function"]["arguments"])
        if not isinstance(args, dict):
            raise ValueError("Tool arguments must be a JSON object.")
        result = await session.call_tool(name, args)
        content = text_result(result)
    except Exception as exc:
        content = json.dumps({"isError": True, "error": str(exc)}, ensure_ascii=False)
    return {"role": "tool", "tool_call_id": call["id"], "content": content}


async def run_turn(session, client, endpoint, model, extra, messages, tools, rounds):
    allowed = {t["function"]["name"] for t in tools}
    for _ in range(rounds):
        response = await client.post(endpoint + "/chat/completions", json={
            **extra, "model": model, "messages": messages, "tools": tools, "stream": False})
        raise_for_model_error(response)
        message = response.json()["choices"][0]["message"]
        message["role"] = "assistant"
        messages.append(message)  # preserve provider reasoning_content when required
        calls = message.get("tool_calls") or []
        if not calls:
            return message.get("content") or ""
        for call in calls:  # CAD calls are always sequential
            print("MCP " + call["function"]["name"], file=sys.stderr)
            messages.append(await tool_reply(session, call, allowed))
    raise RuntimeError("Maximum model rounds reached; completed CAD actions remain in SolidWorks.")


async def main_async(args):
    config = args.config or (ROOT / "providers.local.json" if (ROOT / "providers.local.json").exists()
                             else ROOT / "providers.example.json")
    load_local_env(args.env_file or ROOT / ".env.local")
    if args.interactive_setup:
        prompt_provider(config, args.provider, args.model, force_key=args.check_api)
    base, model, key, extra = resolve_provider(config, args.provider, args.model)
    if args.check_config:
        print(json.dumps({"provider": args.provider, "base_url": base,
                          "model": model, "key_present": bool(key),
                          "api_called": False}, ensure_ascii=False))
        return
    if args.check_api:
        headers = {"Authorization": "Bearer " + key} if key else {}
        async with httpx.AsyncClient(headers=headers, timeout=60, follow_redirects=False) as client:
            print(await check_model_api(client, base, model, extra, args.provider))
        return
    # Fail early on configuration before starting CAD or issuing paid requests.
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")],
                                    cwd=str(ROOT), env={**os.environ, "PYTHONUTF8": "1"})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            inventory = await session.list_tools()
            tools = [as_function(t) for t in inventory.tools]
            if args.read_only:
                tools = [as_function(t) for t in inventory.tools if t.annotations and t.annotations.readOnlyHint]
            messages = [{"role": "system", "content": SYSTEM}]
            headers = {"Authorization": "Bearer " + key} if key else {}
            async with httpx.AsyncClient(headers=headers, timeout=120, follow_redirects=False) as client:
                prompt = args.prompt
                while True:
                    if not prompt:
                        prompt = await asyncio.to_thread(input, "CAD> ")
                    if prompt.strip().lower() in {"exit", "quit"}:
                        return
                    messages.append({"role": "user", "content": prompt})
                    print(await run_turn(session, client, base, model, extra, messages, tools, args.max_rounds))
                    if args.prompt:
                        return
                    prompt = None


def exception_leaves(exc):
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            yield from exception_leaves(child)
    else:
        yield exc


def show_expected_error(exc):
    if isinstance(exc, httpx.HTTPError):
        # HTTPX exception strings can contain URLs; never echo request credentials.
        return f"网络请求失败（{type(exc).__name__}），请检查网络、代理和连接超时。"
    return str(exc)


def main():
    parser = argparse.ArgumentParser(description="OpenAI-compatible model -> SolidWorks 2024 MCP")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", help="Use this model without asking for a model name")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--interactive-setup", action="store_true")
    parser.add_argument("--check-config", action="store_true",
                        help="Validate settings without calling the API or starting CAD")
    parser.add_argument("--check-api", action="store_true",
                        help="Send one short model request without starting MCP or CAD")
    parser.add_argument("--prompt")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=12, choices=range(1, 41))
    args = parser.parse_args()
    if args.check_config and args.check_api:
        parser.error("--check-config and --check-api cannot be used together")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main_async(args))
    except ExceptionGroup as exc:
        # MCP's async task groups wrap errors raised in the caller's API request.
        leaves = list(exception_leaves(exc))
        if not all(isinstance(item, (ValueError, KeyError, RuntimeError, httpx.HTTPError)) for item in leaves):
            raise
        for message in dict.fromkeys(show_expected_error(item) for item in leaves):
            print(message, file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, KeyError, RuntimeError, httpx.HTTPError) as exc:
        print(show_expected_error(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

