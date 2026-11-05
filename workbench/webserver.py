from __future__ import annotations

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import unquote, urlsplit
import urllib.request
import webbrowser

from .engine import WorkbenchEngine, safe_error
from .jobs import JobManager
from .settings import ROOT, STATE_ROOT, SettingsStore, UserFacingError
from app_runtime import INSTANCE_MUTEX, installation_status
from .reference_inputs import ReferenceStore, MAX_IMAGE_BYTES
from .cad_inputs import CadStore,MAX_CAD_BYTES
from .drawing_inputs import DrawingStore,MAX_DRAWING_BYTES

VERSION = "0.6.0-rc1"
WEB_ROOT = Path(__file__).resolve().parent / "web"
APP_ID = "local-solidworks-research-workbench"


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        # Windows SO_REUSEADDR permits another process to share a listening port.
        # A fresh install must never serve a different instance's user state.
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, settings=None, manager=None):
        self.settings = settings or SettingsStore()
        self.engine = WorkbenchEngine(self.settings)
        self.manager = manager or JobManager(self.engine)
        self.references = ReferenceStore(self.settings.root / "uploads")
        self.cad_store = CadStore(self.settings.root / "cad_uploads")
        self.drawing_store = DrawingStore(self.settings.root / 'drawing_uploads',self.references)
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        from .magpie import MagpieService
        self.magpie = MagpieService(self.settings, self.origin)

    def server_close(self):
        if hasattr(self, 'magpie'): self.magpie.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server: WorkbenchServer
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def send_bytes(self, data, content_type, status=200, download=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if download:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(download))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value, status=200):
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def host_ok(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def reject_mutation(self, message):
        # Drain small denied bodies so Windows does not reset before the 403 arrives.
        self.close_connection = True
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if 0 < size <= 65536:
                self.connection.settimeout(2)
                self.rfile.read(size)
        except (OSError, ValueError):
            pass
        self.send_json({"error": message}, 403)

    def do_GET(self):
        if not self.host_ok():
            self.send_json({"error": "Host不可用。"}, 403)
            return
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/health":
                self.send_json({"ok": True, "app": APP_ID, "version": VERSION})
            elif path == "/api/state":
                self.send_json({"version": VERSION, "settings": self.server.settings.public(),
                    "jobs": self.server.manager.list(), "active_job": self.server.manager.active,
                    "modules": self.server.manager.registry.public(),
                    "environment": installation_status(), "magpie": self.server.magpie.public()})
            elif path == '/api/magpie':
                self.send_json(self.server.magpie.public())
            elif path.startswith("/api/uploads/"):
                file, _ = self.server.references.get(path.removeprefix("/api/uploads/"))
                self.send_bytes(file.read_bytes(), "image/png")
            elif path.startswith("/api/jobs/"):
                self.send_json(self.server.manager.get(path.removeprefix("/api/jobs/")))
            elif path.startswith("/api/artifacts/"):
                rest = path.removeprefix("/api/artifacts/").split("/", 1)
                if len(rest) != 2:
                    raise UserFacingError("文件地址无效。")
                directory = self.server.manager.directory(rest[0])
                file = (directory / rest[1]).resolve()
                if not file.is_relative_to(directory) or not file.is_file() or file.name in {"task.json", "task.tmp"}:
                    raise UserFacingError("文件不可用。")
                content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                self.send_bytes(file.read_bytes(), content_type,
                    download=None if file.suffix.lower() in {".png", ".bmp", ".jpg", ".jpeg"} else file.name)
            else:
                name = "index.html" if path == "/" else path.lstrip("/")
                if name not in {"index.html", "app.css", "app.js"}:
                    self.send_json({"error": "页面不存在。"}, 404)
                    return
                file = WEB_ROOT / name
                data = file.read_bytes()
                if name == "index.html":
                    data = data.replace(b"__APP_TOKEN__", self.server.token.encode("ascii"))
                self.send_bytes(data, {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8"}[name])
        except UserFacingError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": safe_error(exc)}, 500)

    def do_POST(self):
        if self.host_ok() and urlsplit(self.path).path == '/magpie-bridge/v1/chat/completions':
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 50_000_000: raise UserFacingError('渠道请求长度无效。')
                self.send_json(self.server.magpie.forward(self.rfile.read(size), self.headers.get('Authorization')))
            except Exception as exc:
                self.send_json({'error': {'message': safe_error(exc), 'type': 'local_channel_error'}}, 400)
            return
        if not self.host_ok() or not secrets.compare_digest(self.headers.get("X-App-Token", ""), self.server.token):
            self.reject_mutation("请从本机应用页面执行此操作。")
            return
        if self.headers.get("Origin") not in {None, self.server.origin}:
            self.reject_mutation("来源不被允许。")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            path = urlsplit(self.path).path
            if path == '/api/drawing-uploads':
                if not 0<size<=MAX_DRAWING_BYTES:
                    self.close_connection=True
                    raise UserFacingError('每张图纸最多20MB。')
                raw=self.rfile.read(size)
                if len(raw)!=size:raise UserFacingError('图纸上传不完整。')
                self.send_json(self.server.drawing_store.add(raw,unquote(self.headers.get('X-File-Name','drawing.dxf'))),201)
                return
            if path == '/api/cad-uploads':
                if not 0<size<=MAX_CAD_BYTES:
                    self.close_connection=True
                    raise UserFacingError('每个零件文件最多50MB。')
                raw=self.rfile.read(size)
                if len(raw)!=size:raise UserFacingError('零件文件上传不完整。')
                self.send_json(self.server.cad_store.add(raw,unquote(self.headers.get('X-File-Name','part.SLDPRT'))),201)
                return
            if path == "/api/uploads":
                if not 0 < size <= MAX_IMAGE_BYTES:
                    self.close_connection = True
                    raise UserFacingError("每张图片最多8MB。")
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise UserFacingError("图片上传不完整，请重新上传。")
                self.send_json(self.server.references.add(raw, unquote(self.headers.get("X-File-Name", "参考图片"))), 201)
                return
            if size < 0 or size > 65536:
                raise UserFacingError("输入内容过长。")
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise UserFacingError("请求格式无效。")
            path = urlsplit(self.path).path
            if path == '/api/magpie':
                action = data.get('action')
                if action in {'save', 'start', 'test'} and self.server.manager.active:
                    raise UserFacingError('请等待当前 CAD 任务结束后更改渠道。')
                if action == 'save': result = self.server.magpie.save(data)
                elif action == 'start': result = self.server.magpie.start()
                elif action == 'refresh': result = self.server.magpie.refresh()
                elif action == 'checkin': result = self.server.magpie.checkin()
                elif action == 'test': result = self.server.magpie.test_models()
                elif action == 'manage': result = self.server.magpie.open_management()
                elif action == 'open_claim':
                    webbrowser.open('https://www.modelscope.cn/magicube/usage'); result = self.server.magpie.public()
                else: raise UserFacingError('不支持的渠道操作。')
                self.send_json(result)
                return
            if path == '/api/review-previews':
                self.send_json(self.server.manager.submit_preview_review(str(data.get('job_id',''))),201)
                return
            if path == "/api/settings":
                self.send_json({"settings": self.server.settings.save(data.get("settings", {}), data.get("keys", {}))})
            elif path == "/api/keys/remove":
                provider = data.get("provider")
                settings = self.server.settings.read()
                if provider not in settings["providers"]:
                    raise UserFacingError("供应商不存在。")
                self.server.settings.vault.remove(provider, settings["providers"][provider]["base_url"])
                self.send_json({"settings": self.server.settings.public()})
            elif path == "/api/test":
                self.send_json(asyncio.run(self.server.engine.test_connections()))
            elif path == "/api/jobs":
                references = self.server.references.resolve(data.get("reference_ids", []))
                cad_inputs = self.server.cad_store.resolve(data.get('cad_ids',[]))
                drawings = self.server.drawing_store.resolve(data.get('drawing_ids',[]))
                for _,metadata in drawings:
                    for ref in metadata.get('references',[]):
                        if not any(r['id']==ref['id'] for _,r in references):references.append(self.server.references.get(ref['id']))
                self.send_json(self.server.manager.submit(data.get("message", ""), data.get("previous_job_id"),
                    data.get("module_id", "solidworks"), references, data.get("reference_mode", "dimensions"),cad_inputs,drawings), 202)
            elif path == "/api/stop":
                self.send_json(self.server.manager.stop(data.get("job_id")))
            elif path == "/api/open-folder":
                os.startfile(str(self.server.manager.directory(data.get("job_id"))))
                self.send_json({"ok": True})
            elif path == "/api/shutdown":
                if self.server.manager.active:
                    raise UserFacingError("当前任务仍在执行，请先停止任务，待当前操作结束后退出。")
                self.send_json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send_json({"error": "接口不存在。"}, 404)
        except (ValueError, TypeError):
            self.send_json({"error": "请求格式无效。"}, 400)
        except UserFacingError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": safe_error(exc)}, 500)


def existing_instance():
    path = STATE_ROOT / "instance.json"
    if not path.is_file():
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        port = int(info["port"])
        if not 1024 <= port <= 65535:
            return None
        url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/health", timeout=2) as response:
            if json.load(response).get("app") == APP_ID:
                return url
    except Exception:
        pass
    return None


def main(open_browser=False, requested_port=8767):
    import win32api
    import win32event
    mutex = win32event.CreateMutex(None, False, INSTANCE_MUTEX)
    if win32api.GetLastError() == 183:
        for _ in range(20):
            url = existing_instance()
            if url:
                if open_browser:
                    webbrowser.open(url)
                win32api.CloseHandle(mutex)
                return
            time.sleep(0.25)
        win32api.CloseHandle(mutex)
        raise UserFacingError("应用正在启动，请稍后再打开。")
    server = None
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        for port in range(requested_port, requested_port + 12):
            try:
                server = WorkbenchServer(("127.0.0.1", port))
                break
            except OSError:
                continue
        if server is None:
            raise UserFacingError("本机应用端口暂不可用，请稍后重试。")
        (STATE_ROOT / "instance.json").write_text(json.dumps({"port": server.server_port, "pid": os.getpid(), "version": VERSION}), encoding="utf-8")
        if open_browser:
            webbrowser.open(server.origin)
        server.serve_forever(poll_interval=0.25)
    finally:
        if server:
            server.server_close()
            instance = STATE_ROOT / "instance.json"
            if instance.exists():
                instance.unlink()
        win32api.CloseHandle(mutex)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    main(args.open, args.port)
