"""Two frozen executables share this entry point; only the MCP one has stdio."""
from __future__ import annotations

import multiprocessing
from pathlib import Path
import sys


def main():
    multiprocessing.freeze_support()
    if Path(sys.executable).stem.casefold() == "solidworksmcp" or "--mcp-server" in sys.argv:
        if "--mcp-server" in sys.argv:
            sys.argv.remove("--mcp-server")
        from server import load_server
        load_server().main()
    elif "--diagnose" in sys.argv:
        import asyncio
        import json
        target = Path(sys.argv[sys.argv.index("--diagnose") + 1])
        from release_tools.diagnostics import diagnose
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            report = asyncio.run(diagnose())
        except Exception as exc:
            import traceback
            report = {"diagnostic_failed": True, "error_type": type(exc).__name__,
                      "traceback": traceback.format_exc(), "model_called": False, "cad_connected": False}
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if report.get("diagnostic_failed"):
            raise SystemExit(1)
    else:
        try:
            from workbench.webserver import main as run_ui
            run_ui(open_browser="--no-browser" not in sys.argv)
        except Exception as exc:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                "程序启动失败，请保留配置并联系维护者。\n错误类型：" + type(exc).__name__,
                "SolidWorks AI", 0x10)


if __name__ == "__main__":
    main()
