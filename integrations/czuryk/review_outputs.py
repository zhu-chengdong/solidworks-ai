"""Locate deliverables independently of the chosen preview subdirectory."""
from pathlib import Path


def expected_outputs(native_path, preview_directory, allowed_root):
    root = Path(allowed_root).resolve()
    previews = Path(preview_directory).resolve()
    native = Path(native_path).resolve() if native_path else previews/'model.SLDPRT'
    if not previews.is_relative_to(root):
        raise ValueError('Preview directory escapes output root')
    delivery = native.parent if native.is_relative_to(root) else previews
    steps = sorted(delivery.glob('*.step')) + sorted(delivery.glob('*.stp'))
    return [str(native)] + [str(p) for p in (steps or [delivery/'model.step'])]
