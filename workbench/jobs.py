from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid

from .engine import JobStopped, safe_error, scrub, underlying_user_error
from .settings import ARTIFACT_ROOT, KEY_PATTERN, UserFacingError, redact
from .modules import Module, ModuleRegistry
from .reference_inputs import pin_references
from .cad_inputs import pin_cad_inputs
from .drawing_inputs import pin_drawings

ACTIVE = {"planning", "executing", "checking", "stopping", "queued"}


def now():
    return datetime.now(timezone.utc).isoformat()


class Job:
    def __init__(self, message, root=ARTIFACT_ROOT, previous_context=None, module_id="solidworks", reference_mode="dimensions"):
        self.id = uuid.uuid4().hex[:16]
        self.created = now()
        self.output_dir = Path(root) / (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + self.id)
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.requests = [message]
        self.module_id = module_id
        self.reference_mode = reference_mode
        self.references = []
        self.cad_inputs = []
        self.drawing_inputs = []
        self.previous_context = previous_context or {}
        self.phase = "queued"
        self.label = "等待处理"
        self.summary = ""
        self.plan = None
        self.events = []
        self.tool_results = []
        self.artifacts = []
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.owns_document = False
        self.owned_title = None
        self.review_reasons = set()
        self.review_status = {}
        self.routing = {}
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.save()

    def public(self):
        with self.lock:
            return scrub({"id": self.id, "created": self.created,
                "requests": list(self.requests), "phase": self.phase, "label": self.label,
                "module_id": self.module_id, "reference_mode": self.reference_mode, "references": list(self.references), "cad_inputs":list(self.cad_inputs), "drawing_inputs":list(self.drawing_inputs),
                "summary": self.summary, "plan": self.plan, "events": list(self.events[-160:]),
                "artifacts": list(self.artifacts), "usage": dict(self.usage),
                "output_dir": str(self.output_dir), "cancel_requested": self.cancel.is_set(),"review_status":dict(self.review_status), "routing":dict(self.routing)})

    def save(self):
        with self.lock:
            data = {**self.public(), "tool_results": scrub(self.tool_results)}
            temporary = self.output_dir / "task.tmp"
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.output_dir / "task.json")

    def event(self, kind, text, **data):
        with self.lock:
            self.events.append(scrub({"time": now(), "kind": kind, "text": redact(text), **data}))
            self.save()

    def set_phase(self, phase, label):
        with self.lock:
            self.phase, self.label = phase, label
            self.event("phase", label, phase=phase)

    def set_plan(self, plan):
        with self.lock:
            self.plan = scrub(plan)
            self.event("plan", plan["summary"])

    def add_usage(self, input_tokens, output_tokens):
        with self.lock:
            self.usage["input_tokens"] += int(input_tokens or 0)
            self.usage["output_tokens"] += int(output_tokens or 0)
            self.save()

    def evidence(self, tool, data):
        with self.lock:
            self.tool_results.append({"tool": tool, "result": scrub(data)})
            self.save()

    def check_stop(self):
        if self.cancel.is_set():
            raise JobStopped("任务已停止。已经完成的操作与文件保留，未发送新的建模操作。")

    def collect_artifacts(self):
        from PIL import Image
        from engineering.previews import active_preview_entries
        with self.lock:
            manifest_path=self.output_dir/'preview-manifest.json'
            try:active=active_preview_entries(self.output_dir)
            except (ValueError,KeyError,OSError):
                active=[];self.review_reasons.add('预览清单或文件校验未通过')
            active_map={v['file']:v for v in active or []}
            try:current_package=Path(json.loads((self.output_dir/'design-acceptance.json').read_text(encoding='utf-8'))['package']).name
            except (OSError,KeyError,ValueError):current_package=None
            for bmp in self.output_dir.rglob("*.bmp"):
                if {'inputs','validation'}.intersection(bmp.relative_to(self.output_dir).parts):
                    continue
                png = bmp.with_suffix(".png")
                if not png.exists():
                    try:
                        with Image.open(bmp) as picture:
                            picture.save(png)
                    except Exception:
                        self.review_reasons.add("部分预览未能读取")
            result = []
            for path in sorted(self.output_dir.rglob("*")):
                if {'inputs','validation'}.intersection(path.relative_to(self.output_dir).parts):
                    continue
                if path.is_file() and path.name not in {"task.json", "task.tmp",'cad-inputs.json','engineering-progress.json'} and not path.name.startswith('~$') and path.stat().st_size:
                    relative = path.relative_to(self.output_dir).as_posix()
                    is_image=path.suffix.lower() in {".png", ".jpg", ".jpeg"}
                    preferred=relative in active_map
                    result.append({"name": relative, "size": path.stat().st_size,
                                   "preview":preferred if manifest_path.exists() else is_image,
                                   "archived_preview":is_image and manifest_path.exists() and not preferred,
                                   "view_label":active_map.get(relative,{}).get('label'),
                                   "view_id":active_map.get(relative,{}).get('id'),
                                   "current_delivery":relative==current_package,
                                   "url": f"/api/artifacts/{self.id}/{relative}"})
            self.artifacts = result
            self.save()

    def finish(self, phase, summary):
        with self.lock:
            self.summary = redact(summary)
            labels = {"completed": "任务完成", "clarify": "需要补充信息", "blocked": "需要处理",
                      "failed": "任务未完成", "review_required": "已执行，待复核", "cancelled": "任务已停止"}
            if phase=='review_required' and self.review_status.get('state')=='passed':labels[phase]='预览复核通过，工程待确认'
            self.set_phase(phase, labels.get(phase, phase))


class JobManager:
    def __init__(self, engine, root=ARTIFACT_ROOT, registry=None):
        self.engine, self.root = engine, Path(root)
        self.registry = registry or ModuleRegistry([Module("solidworks", "SolidWorks 助手", ("text", "image"), engine)])
        self.jobs = {}
        self.recent = []
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cad-workbench")
        self.active = None
        self.load_history()

    def load_history(self):
        if not self.root.is_dir():
            return
        files = sorted(self.root.glob("*/task.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:40]
        for file in files:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if data.get("phase") in ACTIVE:
                    data["phase"], data["label"] = "review_required", "上次任务已中断，需核对结果"
                data["output_dir"] = str(file.parent)
                self.recent.append(scrub(data))
            except Exception:
                continue

    def get(self, job_id):
        with self.lock:
            if job_id in self.jobs:
                return self.jobs[job_id].public()
            for item in self.recent:
                if item.get("id") == job_id:
                    return item
        raise UserFacingError("没有找到这个任务。")

    def list(self):
        with self.lock:
            fresh = [job.public() for job in self.jobs.values()]
            ids = {item["id"] for item in fresh}
            return sorted(fresh + [item for item in self.recent if item.get("id") not in ids],
                          key=lambda item: item["created"], reverse=True)[:40]

    def submit(self, message, previous_id=None, module_id="solidworks", references=None, reference_mode="dimensions", cad_inputs=None, drawing_inputs=None):
        module = self.registry.require(module_id)
        references = references or []
        cad_inputs = cad_inputs or []
        drawing_inputs = drawing_inputs or []
        previous=self.get(previous_id) if previous_id else None
        if previous and previous.get('drawing_inputs') and not drawing_inputs:
            previous_dir=Path(previous['output_dir']).resolve()
            if not previous_dir.is_relative_to(self.root.resolve()):raise UserFacingError('原任务图纸路径不可用。')
            for item in previous['drawing_inputs']:
                source=(previous_dir/item['file']).resolve()
                if not source.is_relative_to(previous_dir/'inputs'/'drawings'):raise UserFacingError('原任务图纸路径不可用。')
                drawing_inputs.append((source,item))
        vector=any(meta.get('kind')=='vector' for _,meta in drawing_inputs)
        if vector and (references or cad_inputs or module_id!='solidworks'):raise UserFacingError('DXF/DWG精确建模请单独上传一份图纸。')
        if reference_mode not in {"dimensions", "approximate"}:
            raise UserFacingError("请选择按尺寸建模或外观尝试。")
        if references and "image" not in module.inputs:
            raise UserFacingError("当前模块不支持参考图片。")
        message = str(message).strip()
        if not message or len(message) > 10000:
            raise UserFacingError("请输入1到10000字的需求。")
        if KEY_PATTERN.search(message):
            raise UserFacingError("密钥请填在设置中，自然语言输入区不接收密钥。")
        # Validate only this app's credentials before opening a CAD session.
        settings = module.engine.settings.read()
        from .magpie import read_config, MODELSCOPE
        routing = read_config(module.engine.settings)
        if vector:
            pass # Exact vector route does not resolve providers or credentials.
        elif routing['enabled']:
            if not module.engine.settings.vault.has('modelscope', MODELSCOPE): raise UserFacingError('请先在额度与路由中保存魔搭令牌。')
        else:
            module.engine.settings.role("planner", settings)
            module.engine.settings.role("executor", settings)
        vision = settings["roles"]["planner"].get("vision", settings["roles"]["planner"]["provider"] == "openai")
        if references and not vision and not routing['enabled']:
            raise UserFacingError("请在模型设置中选择支持图片的理解模型，并启用图片输入。")
        with self.lock:
            if self.active:
                raise UserFacingError("当前任务尚未结束，请等待或先停止当前任务。")
            previous = self.get(previous_id) if previous_id else None
            if previous and previous.get("module_id", "solidworks") != module_id:
                raise UserFacingError("不同模块的任务需要分别新建。")
            if previous_id in self.jobs and previous and previous.get("phase") == "clarify":
                job = self.jobs[previous_id]
                pin_references(job, references)
                pin_cad_inputs(job,cad_inputs)
                pin_drawings(job,drawing_inputs)
                job.requests.append(message)
                job.cancel.clear()
                job.set_phase("queued", "继续理解补充信息")
            else:
                context = {"requests": previous.get("requests"), "summary": previous.get("summary"),
                           "plan": previous.get("plan"), "output_dir": previous.get("output_dir")} if previous else {}
                job = Job(message, self.root, context, module_id, reference_mode)
                pin_references(job, references)
                if previous and previous.get('cad_inputs'):
                    previous_dir=Path(previous['output_dir']).resolve()
                    if not previous_dir.is_relative_to(self.root.resolve()):raise UserFacingError('原任务零件路径不可用。')
                    existing_ids={metadata['id'] for _,metadata in cad_inputs}
                    inherited=[]
                    for item in previous['cad_inputs']:
                        source=(previous_dir/item['file']).resolve()
                        if not source.is_relative_to(previous_dir/'inputs'/'cad'):raise UserFacingError('原任务零件路径不可用。')
                        if item['id'] not in existing_ids:inherited.append((source,item))
                    cad_inputs=inherited+cad_inputs
                pin_cad_inputs(job,cad_inputs)
                pin_drawings(job,drawing_inputs)
                self.jobs[job.id] = job
            self.active = job.id
            self.pool.submit(self._run, job)
            return job.public()

    def submit_preview_review(self,job_id):
        from .preview_review import clone_for_preview_review
        with self.lock:
            if self.active:raise UserFacingError('当前任务尚未结束，请稍后重新复核。')
            source=self.get(job_id)
            settings=self.engine.settings.read()
            from .magpie import read_config, MODELSCOPE
            if read_config(self.engine.settings)['enabled']:
                if not self.engine.settings.vault.has('modelscope', MODELSCOPE): raise UserFacingError('请先保存魔搭令牌。')
            else:
                for role in ('planner','executor'):self.engine.settings.role(role,settings)
            job=clone_for_preview_review(source,self.root)
            self.jobs[job.id]=job;self.active=job.id
            self.pool.submit(self._run,job,True)
            return job.public()

    def _run(self, job,preview_review=False):
        try:
            engine=self.registry.require(job.module_id).engine
            asyncio.run(engine.recheck_previews(job) if preview_review else engine.run(job))
        except JobStopped as exc:
            job.collect_artifacts()
            job.finish("cancelled", str(exc))
        except BaseException as exc:
            if job.review_status:job.review_status['state']='unresolved'
            job.collect_artifacts()
            phase = "cancelled" if isinstance(underlying_user_error(exc), JobStopped) else ("review_required" if job.owns_document else "failed")
            job.finish(phase, safe_error(exc))
        finally:
            with self.lock:
                self.active = None

    def stop(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job_id != self.active:
                return self.get(job_id)
            job.cancel.set()
            job.set_phase("stopping", "正在停止；当前SolidWorks操作结束后不再继续")
            return job.public()

    def directory(self, job_id):
        data = self.get(job_id)
        path = Path(data["output_dir"]).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_dir():
            raise UserFacingError("任务目录不可用。")
        return path
