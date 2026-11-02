"""Validate uploaded images and pin immutable normalized copies to each job."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import uuid
import warnings

from PIL import Image, ImageOps

from app_runtime import STATE_ROOT
from .settings import UserFacingError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REFERENCES = 4


class ReferenceStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else STATE_ROOT / "uploads"

    def add(self, raw, name):
        if not 0 < len(raw) <= MAX_IMAGE_BYTES:
            raise UserFacingError("每张图片最多8MB。")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as im:
                    if im.format not in {"PNG", "JPEG", "WEBP"} or getattr(im, "n_frames", 1) != 1 or im.width * im.height > 40_000_000:
                        raise ValueError()
                    im.load()
                    picture = ImageOps.exif_transpose(im).convert("RGB")
                    picture.thumbnail((2048, 2048))
        except Exception:
            raise UserFacingError("请上传单张PNG、JPG或WebP图片，像素总数不超过4000万。") from None
        asset_id = uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / (asset_id + ".png")
        picture.save(target, format="PNG")
        display = Path(str(name).replace("\\", "/")).name[:120]
        display = "".join(c for c in display if ord(c) >= 32) or "参考图片"
        metadata = {"id": asset_id, "name": display, "width": picture.width, "height": picture.height,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "original_sha256": hashlib.sha256(raw).hexdigest(), "url": f"/api/uploads/{asset_id}"}
        target.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        return metadata

    def get(self, asset_id):
        if not isinstance(asset_id, str) or not re.fullmatch(r"[0-9a-f]{32}", asset_id):
            raise UserFacingError("参考图片不存在，请重新上传。")
        target = self.root / (asset_id + ".png")
        try:
            meta = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
            if hashlib.sha256(target.read_bytes()).hexdigest() != meta['sha256']:
                raise ValueError()
            return target, meta
        except (OSError, ValueError, KeyError):
            raise UserFacingError("参考图片不可用，请重新上传。") from None

    def resolve(self, ids):
        if not isinstance(ids, list) or len(ids) > MAX_REFERENCES or len(set(ids)) != len(ids):
            raise UserFacingError("每个任务最多上传4张不同图片。")
        return [self.get(item) for item in ids]


def pin_references(job, references):
    if len(job.references) + len(references) > MAX_REFERENCES:
        raise UserFacingError("每个任务最多使用4张参考图片。")
    for source, metadata in references:
        if any(r['id'] == metadata['id'] for r in job.references):
            continue
        target = job.output_dir / "inputs" / (metadata['id'] + ".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata['sha256']:
            raise UserFacingError("参考图片校验失败，请重新上传。")
        target.write_bytes(raw)
        job.references.append({**metadata, "file": target.relative_to(job.output_dir).as_posix(),
            "url": f"/api/artifacts/{job.id}/inputs/{target.name}"})
    job.save()
