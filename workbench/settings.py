from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit

from app_runtime import RESOURCE_ROOT as ROOT, STATE_ROOT, ARTIFACT_ROOT
DEFAULTS = {
    "providers": {
        "openai": {"title": "OpenAI", "base_url": "https://api.openai.com/v1", "api_style": "responses"},
        "deepseek": {"title": "DeepSeek", "base_url": "https://api.deepseek.com", "api_style": "chat_completions"},
        "custom": {"title": "其他兼容API", "base_url": "", "api_style": "chat_completions"},
    },
    "roles": {
        "planner": {"provider": "openai", "model": "gpt-6.1-sol", "vision": True},
        "executor": {"provider": "openai", "model": "gpt-5.4-mini"},
    },
    "max_turns": 14,
}
KEY_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|ms-[A-Za-z0-9_-]{16,})\b")


class UserFacingError(RuntimeError):
    pass


def redact(text):
    return KEY_PATTERN.sub("[密钥已隐藏]", str(text))


def canonical_url(value: str, allow_empty=False):
    value = value.strip().rstrip("/")
    if not value and allow_empty:
        return ""
    parsed = urlsplit(value)
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not parsed.hostname or (parsed.scheme != "https" and not (local and parsed.scheme == "http")):
        raise UserFacingError("远程API地址需要使用HTTPS，本机服务可使用HTTP。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UserFacingError("API地址只能包含服务地址和路径，不能包含密钥、查询参数或账号。")
    return value


class CredentialVault:
    """Only access credentials created for this app and this exact endpoint."""
    @staticmethod
    def target(provider, base_url):
        digest = hashlib.sha256(base_url.encode("utf-8")).hexdigest()[:24]
        return f"ResearchAutomation/SolidWorks/{provider}/{digest}"

    def put(self, provider, base_url, key):
        import win32cred
        key = key.strip()
        if not key or any(char.isspace() or ord(char) < 32 for char in key):
            raise UserFacingError("请粘贴完整密钥，密钥中不能包含空格或换行。")
        if any(mark in key for mark in ("...", "…", "*")):
            raise UserFacingError("输入的是遮罩或截断内容，请使用创建时保存的完整密钥。")
        try:
            win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": self.target(provider, base_url), "UserName": "科研自动化",
                "CredentialBlob": key, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)
        except Exception:
            raise UserFacingError("本机安全存储写入失败，请从Windows桌面双击启动应用后重试。") from None

    def get(self, provider, base_url):
        import win32cred
        try:
            value = win32cred.CredRead(self.target(provider, base_url), win32cred.CRED_TYPE_GENERIC)["CredentialBlob"]
            return value.decode("utf-16-le") if isinstance(value, bytes) else value
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168 or (exc.args and exc.args[0] == 1168):
                return ""
            code = getattr(exc, 'winerror', None)
            if code is None and exc.args and isinstance(exc.args[0], int):
                code = exc.args[0]
            hint = f"{type(exc).__name__}/{code}" if isinstance(code, int) else type(exc).__name__
            raise UserFacingError(f"无法读取本应用的本机安全存储，请重新打开应用（{hint}）。") from None

    def has(self, provider, base_url):
        return bool(base_url and self.get(provider, base_url))

    def remove(self, provider, base_url):
        import win32cred
        try:
            win32cred.CredDelete(self.target(provider, base_url), win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            if not (getattr(exc, "winerror", None) == 1168 or (exc.args and exc.args[0] == 1168)):
                raise UserFacingError("移除本机密钥失败，请重试。") from None


class SettingsStore:
    def __init__(self, root=STATE_ROOT, vault=None):
        self.root = Path(root)
        self.vault = vault or CredentialVault()
        self.lock = threading.RLock()
        self.path = self.root / "settings.json"

    def read(self):
        with self.lock:
            if self.path.is_file():
                try:
                    return self.validate(json.loads(self.path.read_text(encoding="utf-8")))
                except (ValueError, TypeError, KeyError):
                    raise UserFacingError("本机设置文件损坏，请保留文件并联系维护者。") from None
            return copy.deepcopy(DEFAULTS)

    @staticmethod
    def validate(settings):
        if not isinstance(settings, dict):
            raise UserFacingError("设置格式无效。")
        result = copy.deepcopy(DEFAULTS)
        for name in result["providers"]:
            provided = settings.get("providers", {}).get(name, {})
            base = canonical_url(str(provided.get("base_url", result["providers"][name]["base_url"])), allow_empty=name == "custom")
            style = provided.get("api_style", result["providers"][name]["api_style"])
            if style not in {"responses", "chat_completions"}:
                raise UserFacingError("请选择受支持的API接口类型。")
            if name == "openai" and base != DEFAULTS["providers"][name]["base_url"]:
                raise UserFacingError("OpenAI使用官方地址，其他服务请填写到兼容API设置。")
            if name == "deepseek" and base != DEFAULTS["providers"][name]["base_url"]:
                raise UserFacingError("DeepSeek使用官方地址，其他服务请填写到兼容API设置。")
            result["providers"][name].update(base_url=base, api_style=style)
        for role in result["roles"]:
            item = settings.get("roles", {}).get(role, result["roles"][role])
            provider, model = item.get("provider"), str(item.get("model", "")).strip()
            if provider not in result["providers"] or not model or len(model) > 160 or KEY_PATTERN.search(model):
                raise UserFacingError("请为两个角色选择供应商并填写模型名称。")
            if any(char.isspace() or ord(char) < 32 for char in model):
                raise UserFacingError("模型名称中不能包含空格或换行。")
            result["roles"][role] = {"provider": provider, "model": model}
            effort=item.get('reasoning_effort','auto')
            allowed={'auto','none','low','medium','high','xhigh','max'}
            if effort not in allowed or (provider=='deepseek' and effort in {'medium','xhigh'}):
                raise UserFacingError('请选择该供应商支持的思考强度；DeepSeek支持关闭、low、high和max。')
            if effort!='auto':result['roles'][role]['reasoning_effort']=effort
            if role == "planner":
                vision = item.get("vision", provider == "openai")
                if not isinstance(vision, bool):
                    raise UserFacingError("图片输入设置无效。")
                result["roles"][role]["vision"] = vision
        try:
            turns = int(settings.get("max_turns", 14))
        except (TypeError, ValueError):
            raise UserFacingError("执行步数需要是整数。") from None
        if not 2 <= turns <= 30:
            raise UserFacingError("执行步数需要在2到30之间。")
        result["max_turns"] = turns
        return result

    def public(self):
        result = self.read()
        for name, item in result["providers"].items():
            item["key_present"] = self.vault.has(name, item["base_url"])
        return result

    def save(self, settings, keys=None):
        validated = self.validate(settings)
        with self.lock:
            for provider, key in (keys or {}).items():
                if provider not in validated["providers"] or not isinstance(key, str):
                    raise UserFacingError("密钥设置格式无效。")
                if key.strip():
                    base = validated["providers"][provider]["base_url"]
                    if not base:
                        raise UserFacingError("请先填写兼容API的服务地址。")
                    self.vault.put(provider, base, key)
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        return self.public()

    def role(self, name, settings=None):
        settings = settings or self.read()
        role = settings["roles"][name]
        profile = settings["providers"][role["provider"]]
        key = self.vault.get(role["provider"], profile["base_url"]) if profile["base_url"] else ""
        if not key:
            title = "理解与规划" if name == "planner" else "执行操作"
            raise UserFacingError(f"请先在设置中保存{title}所用供应商的API密钥。")
        return {**role, **profile, "key": key}
