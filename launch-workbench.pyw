from pathlib import Path
import sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))

try:
    from workbench.webserver import main
    main(open_browser=True)
except Exception as exc:
    # No credential, request body or traceback is written into a launch log.
    import ctypes
    ctypes.windll.user32.MessageBoxW(None,
        "科研自动化启动失败。请保留现有配置并联系维护者。\n错误类型：" + type(exc).__name__,
        "科研自动化", 0x10)
