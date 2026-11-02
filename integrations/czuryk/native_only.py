"""Adapt selected MIT upstream features; never start its server or UI watchdog."""
from __future__ import annotations

import os
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parent / 'source'


def registered_executable():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'SldWorks.Application.32\CLSID') as key:
        clsid = winreg.QueryValue(key, None)
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf'CLSID\{clsid}\LocalServer32') as key:
        value = winreg.QueryValue(key, None).strip()
    return Path(value[1:value.index('"', 1)] if value.startswith('"') else value)


def native_automation(app=None):
    if str(SOURCE) not in sys.path:
        sys.path.insert(0, str(SOURCE))
    import pythoncom
    import win32com.client
    from solidworks_mcp.automation import SolidWorksAutomation
    from solidworks_mcp.automation.com_utils import com_get
    import solidworks_mcp.utils as utilities

    executable = registered_executable()
    utilities.find_solidworks = lambda: str(executable)
    audit = {'ui_recovery_calls': 0, 'window_capture_calls': 0,
             'ui_detection': 'disabled; only native API is used'}

    def disabled_ui_detection(*_args, **_kwargs):
        return {'modal': False, 'checked': False, 'method': 'native_only_adapter'}

    def forbidden_ui(*_args, **_kwargs):
        audit['ui_recovery_calls'] += 1
        raise RuntimeError('UI automation is disabled in this integration')

    def disabled_capture(*_args, **_kwargs):
        audit['window_capture_calls'] += 1
        return {'success': False, 'message': 'Window capture disabled; use native exported previews'}

    # Several upstream modules import these names directly; cover each bound alias.
    for name, module in tuple(sys.modules.items()):
        if not name.startswith('solidworks_mcp.') or module is None:
            continue
        if hasattr(module, 'detect_modal_dialog'):
            module.detect_modal_dialog = disabled_ui_detection
        if hasattr(module, 'resolve_known_dialog'):
            module.resolve_known_dialog = forbidden_ui
        for field in ('capture_ui_problem_screenshot', 'persist_ui_problem_screenshot'):
            if hasattr(module, field):
                setattr(module, field, disabled_capture)

    class NativeOnlyAutomation(SolidWorksAutomation):
        def _resolve_document_template(self, document_type):
            found, source = super()._resolve_document_template(document_type)
            if found or document_type != 'part':
                return found, source
            base = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData'))/'SOLIDWORKS'/'SOLIDWORKS 2024'/'templates'
            candidates = sorted(base.glob('*.prtdot'))
            if len(candidates) == 1:
                return str(candidates[0]), 'version_2024_installed_template'
            return None, source

        def connect(self):
            if self._sw_app is None:
                self._sw_app = win32com.client.DispatchEx('SldWorks.Application.32', clsctx=pythoncom.CLSCTX_LOCAL_SERVER)
            revision = str(com_get(self._sw_app, 'RevisionNumber'))
            if not revision.startswith('32.'):
                raise RuntimeError('This adapter is qualified only for SolidWorks2024')
            self._connected = True
            return self._result(True, 'Connected through native SolidWorks2024 API', data={'version': revision})

        def ui_preflight(self, *_args, **_kwargs):
            return None

        def ui_postflight(self, _tool, result, **_kwargs):
            return result

        def take_screenshot(self, *_args, **_kwargs):
            return disabled_capture()

        def observe_model(self, *_args, **_kwargs):
            return disabled_capture()

        def restart_solidworks(self, *_args, **_kwargs):
            return forbidden_ui()

    automation = NativeOnlyAutomation()
    automation._sw_app = app
    if app is not None:
        automation._connected = True
    automation.native_only_audit = audit
    return automation
