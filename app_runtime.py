"""Paths and child-process entry points shared by source and Windows bundles."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys


def layout(*, frozen=None, executable=None, resource_root=None, environment=None):
    environment = os.environ if environment is None else environment
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    resources = Path(resource_root or Path(__file__).resolve().parent).resolve()
    executable = Path(executable or sys.executable).resolve()
    override = environment.get("SOLIDWORKS_AI_DATA_HOME")
    if override:
        data = Path(override).expanduser()
        if not data.is_absolute():
            raise ValueError("SOLIDWORKS_AI_DATA_HOME must be an absolute directory")
    elif frozen:
        local = environment.get("LOCALAPPDATA")
        if not local:
            raise RuntimeError("Windows LOCALAPPDATA is unavailable")
        data = Path(local) / "SolidWorksAI"
    else:
        data = resources
    data = data.resolve()
    if frozen:
        command, args = executable.parent / "SolidWorksMCP.exe", []
    else:
        candidate = resources / ".venv" / "Scripts" / "python.exe"
        command = candidate if candidate.is_file() else executable
        args = [str(resources / "server.py")]
    return resources, data, command, args


RESOURCE_ROOT, DATA_ROOT, MCP_COMMAND, MCP_ARGS = layout()
STATE_ROOT = DATA_ROOT / "runtime" / "workbench"
ARTIFACT_ROOT = DATA_ROOT / "artifacts" / "Workbench"
INSTANCE_MUTEX = "Local\\SolidWorksAI." + hashlib.sha256(str(DATA_ROOT).casefold().encode()).hexdigest()[:20]


def installation_status():
    """Read COM registration only; never launch or operate SolidWorks."""
    ready = False
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application.32\CLSID"):
                ready = True
        except OSError:
            pass
    return {"supported_solidworks": 2024, "solidworks_registered": ready,
            "data_directory": str(DATA_ROOT), "bundled": bool(getattr(sys, "frozen", False))}
