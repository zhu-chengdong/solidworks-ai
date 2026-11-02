"""Model-independent SolidWorks 2024 MCP entry point. No desktop automation."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from engineering.call_lifecycle import wait_for_native_result
from contextlib import contextmanager, redirect_stdout

from app_runtime import RESOURCE_ROOT as ROOT, DATA_ROOT
ENGINE = ROOT / "vendor" / "solidworks-automation"
os.environ.setdefault("SW_MCP_OUTPUT_ROOT", str(DATA_ROOT / "artifacts"))
os.environ.setdefault("SW_MCP_QUEUE_DIR", str(DATA_ROOT / "runtime" / "ledger"))
os.environ.setdefault("PYTHONUTF8", "1")
for location in (ENGINE, ENGINE / "scripts", ENGINE / "mcp-server"):
    sys.path.insert(0, str(location))


@contextmanager
def cad_mutex(timeout_ms=30000):
    """Serialize CAD across every stdio/HTTP instance in this Windows session."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\SolidWorksMCP2024.CAD")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        status = kernel.WaitForSingleObject(handle, timeout_ms)
        if status not in (0, 0x80):
            raise TimeoutError("SolidWorks is busy in another MCP client; retry after it finishes.")
        acquired = True
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def load_server():
    # On this Windows/Conda runtime NumPy's first DLL load in a worker thread can
    # deadlock with Python/AnyIO thread startup. Import before creating any STA.
    import numpy
    import scipy
    import cv2
    import shapely
    import skimage
    import sympy
    from integrations.czuryk.native_only import SOURCE
    if str(SOURCE) not in sys.path:
        sys.path.insert(0, str(SOURCE))
    from solidworks_mcp.automation import SolidWorksAutomation
    spec = importlib.util.spec_from_file_location("sw_mcp_engine", ENGINE / "mcp-server" / "server.py")
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    # Imported libraries sometimes print; stdout belongs exclusively to MCP.
    with redirect_stdout(sys.stderr):
        spec.loader.exec_module(engine)
    engine._MCP_STDOUT = sys.stdout

    import pythoncom
    import win32com.client
    import scripts.sw_connect as connection
    original_connect = connection.connect_solidworks
    session_app = None
    baseline_documents = None

    def connect_2024(*args, **kwargs):
        nonlocal session_app, baseline_documents
        if args:
            if args[0] not in (None, 2024):
                raise ValueError("This MCP endpoint controls SolidWorks 2024 only.")
            args = (2024, *args[1:])
        else:
            if kwargs.get("version") not in (None, 2024):
                raise ValueError("This MCP endpoint controls SolidWorks 2024 only.")
            kwargs["version"] = 2024
        # This machine's SW2024 exposes its class factory but does not register an
        # application-level active object in ROT. DispatchEx was verified to return
        # the existing PID, without opening/closing documents or starting a second UI.
        if session_app is None:
            from scripts.sw_process import solidworks_processes
            before = solidworks_processes()
            if before and len(before) == 1:
                session_app = win32com.client.DispatchEx("SldWorks.Application.32",
                    clsctx=pythoncom.CLSCTX_LOCAL_SERVER)
            else:
                return original_connect(*args, **kwargs)
        version = connection.get_sw_version(session_app)
        if version["year"] != 2024:
            session_app = None
            raise connection.SolidWorksConnectionError("SW_VERSION_MISMATCH", "verify", "Expected SolidWorks 2024.")
        if baseline_documents is None:
            baseline_documents = connection.snapshot_open_documents(session_app, strict=True)
            # The upstream budget counts loaded assembly components too. Preserve
            # them and reserve eight additional documents for this MCP session.
            os.environ.setdefault("SW_MAX_DOCUMENTS", str(len(baseline_documents) + 8))
        model = connection._read_active_document(session_app)
        metadata = {"prog_id": "SldWorks.Application.32", "requested_version": 2024,
            "actual_version": 2024, "actual_revision": version["revision"],
            "process_id": connection.get_com_member(session_app, "GetProcessID"),
            "connection_method": "native_com_class_factory"}
        return (session_app, model, metadata) if kwargs.get("return_metadata") else (session_app, model)

    connection.connect_solidworks = connect_2024
    # One dedicated STA thread prevents cached sketch/feature proxies crossing apartments.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="SW2024-STA",
                                  initializer=pythoncom.CoInitialize)
    original_run = engine._run_locked
    engine._coinitialize = lambda: None  # executor owns COM initialization

    def run_locked(operation, response_format, load_automation=True, timeout_seconds=30):
        def work():
            with cad_mutex():
                return original_run(operation, response_format, load_automation, timeout_seconds)
        future = executor.submit(work)
        try:
            return wait_for_native_result(future,on_wait=lambda:print(
                'NATIVE_CALL_STILL_RUNNING: preserving COM client until SolidWorks returns; no cancellation or replay.',file=sys.stderr,flush=True))
        except Exception as exc:
            return engine._tool_error(exc, response_format)

    engine._run_locked = run_locked
    # SaveAs can resolve duplicate document titles incorrectly on SW2024. The
    # workbench gives each native file a unique task name; also verify every
    # exported part's solid count rather than trusting SaveAs's boolean alone.
    from integrations.czuryk.step_export import export_full_step
    def export_step_verified(model,path):
        app,_=connection.connect_solidworks()
        return export_full_step(app,model,path)['success']
    engine.export_to_step=export_step_verified
    # These five upstream tools capture run_locked during registration. Rebind
    # them explicitly so they also use the same STA and cross-process mutex.
    for name in ("solidworks_inspect_native_geometry", "solidworks_build_round_sweeps",
                 "solidworks_import_step_part", "solidworks_replace_component_preserving_transform",
                 "solidworks_exclude_reviewed_bodies"):
        engine.mcp.remove_tool(name)
    engine._register_native_wire_tools(engine.mcp, lambda **kw: engine.connect_solidworks(**kw),
                                       run_locked, engine.ResponseFormat)
    # Recovery uses window messages/keyboard events in upstream. Do not expose it.
    engine.mcp.remove_tool("solidworks_recover")

    from pydantic import BaseModel, ConfigDict

    class ReferenceBuildInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        spec_path: str
        output_path: str
        component_start: int = 0

    # Resolve the local class before FastMCP inspects postponed annotations.
    globals()["ReferenceBuildInput"] = ReferenceBuildInput

    @engine.mcp.tool(name="solidworks_build_reference")
    def reference_build(params: ReferenceBuildInput) -> str:
        """Create a NEW native part from bounded prism/revolve/loft/aircraft data. No arbitrary code."""
        def operation():
            from integrations.czuryk.reference_build import build_reference
            print("Reference tool: connect on CAD STA", file=sys.stderr, flush=True)
            app, _ = connection.connect_solidworks()
            return build_reference(app, params.spec_path, params.output_path, os.environ["SW_MCP_OUTPUT_ROOT"], params.component_start)
        return run_locked(operation, engine.ResponseFormat.JSON)

    class EngineeringInput(BaseModel):
        model_config=ConfigDict(extra='forbid')
        spec_path:str
        output_dir:str
        stage:int=0
    globals()['EngineeringInput']=EngineeringInput

    @engine.mcp.tool(name='solidworks_execute_design')
    def execute_design(params:EngineeringInput)->str:
        """Execute one saved native stage of a validated part/assembly design. Includes real mates, readback, interference, native files and a dependency ZIP. No code execution."""
        def operation():
            from engineering.native import execute_stage
            app,_=connection.connect_solidworks()
            return execute_stage(app,params.spec_path,params.output_dir,params.stage,os.environ['SW_MCP_OUTPUT_ROOT'])
        return run_locked(operation,engine.ResponseFormat.JSON)

    class PreviewRepairInput(BaseModel):
        model_config=ConfigDict(extra='forbid')
        output_dir:str
    globals()['PreviewRepairInput']=PreviewRepairInput

    @engine.mcp.tool(name='solidworks_repair_design_previews')
    def repair_previews(params:PreviewRepairInput)->str:
        """Re-export verified, labelled views of an existing verified design, once. Never save or rebuild native geometry; preserve old packages."""
        def operation():
            from engineering.previews import repair_design_previews
            app,_=connection.connect_solidworks()
            return repair_design_previews(app,params.output_dir,os.environ['SW_MCP_OUTPUT_ROOT'])
        return run_locked(operation,engine.ResponseFormat.JSON)

    class InputPartInspect(BaseModel):
        model_config=ConfigDict(extra='forbid')
        input_path:str
        sha256:str
    globals()['InputPartInspect']=InputPartInspect

    @engine.mcp.tool(name='solidworks_inspect_input_part',annotations={'readOnlyHint':True})
    def inspect_input_part(params:InputPartInspect)->str:
        """Read real solid volume, bounding box and cylinder faces from an immutable task-pinned SLDPRT. CAD bytes remain local."""
        def operation():
            from engineering.inspect import inspect_input
            app,_=connection.connect_solidworks()
            return inspect_input(app,params.input_path,params.sha256,os.environ['SW_MCP_OUTPUT_ROOT'])
        return run_locked(operation,engine.ResponseFormat.JSON)

    # Preserve the upstream review policy, while declaring the outputs which the
    # workbench actually requires. This removes the unrelated "not declared"
    # warning without changing a single sketch/geometry acceptance threshold.
    engine.mcp.remove_tool('solidworks_review_active')
    globals()['SolidWorksReviewInput'] = engine.SolidWorksReviewInput

    @engine.mcp.tool(name='solidworks_review_active')
    def review_active(params: SolidWorksReviewInput) -> str:
        """Export native previews and check sketches, B-Rep and required native/STEP outputs. Manual intent review remains required."""
        def operation():
            _app, model = engine._active_model_required()
            directory = Path(params.output_dir).resolve()
            root = Path(os.environ['SW_MCP_OUTPUT_ROOT']).resolve()
            if not directory.is_relative_to(root) or Path(params.basename).name != params.basename:
                raise ValueError('Review outputs must stay in the allowed task directory')
            native_path = str(engine.get_com_member(model, 'GetPathName') or directory/'model.SLDPRT')
            from integrations.czuryk.review_outputs import expected_outputs
            expected = expected_outputs(native_path, directory, root)
            report, report_path = engine.run_review(model, str(directory), basename=params.basename, expected_outputs=expected)
            evaluation = report.get('evaluation') or {}
            return {'status': 'failed' if evaluation.get('status') == 'fail' else 'review_required',
                'report_path': report_path, 'evaluation': evaluation, 'checks': report.get('checks'),
                'previews': report.get('previews', []), 'sketch_quality': report.get('sketch_quality'),
                'manual_review_required': True, 'document': engine._model_summary(model)}
        return run_locked(operation, params.response_format)

    engine.mcp.remove_tool('solidworks_update_dimension')
    globals()['SolidWorksDimensionUpdateInput'] = engine.SolidWorksDimensionUpdateInput

    @engine.mcp.tool(name='solidworks_update_dimension')
    def update_dimension(params: SolidWorksDimensionUpdateInput) -> str:
        """Set an exact native driving dimension, force a B-Rep rebuild, then optionally save. Return actual readback and rebuild status."""
        def operation():
            _app, model = engine._active_model_required()
            result = engine.update_dimension_mm(model, params.dimension_name, params.value_mm,
                configuration_mode=params.configuration_mode, configuration_names=params.configuration_names,
                rebuild=False, save=False)
            if result.get('success') and params.rebuild:
                rebuilt = bool(engine.get_com_member(model, 'ForceRebuild3', False))
                result.update(rebuild_success=rebuilt, success=rebuilt, force_rebuild=True)
            result['save_requested'] = params.save
            result['save_success'] = bool(engine.save_document(model)) if result.get('success') and params.save else not params.save
            result['success'] = bool(result.get('success') and result['save_success'])
            result['document'] = engine._model_summary(model)
            return result
        return run_locked(operation, params.response_format)

    @engine.mcp.tool(name="solidworks_mcp_info", annotations={"readOnlyHint": True})
    def integration_info() -> str:
        """Return this endpoint's version, control method and provider independence."""
        return json.dumps({"solidworks_year": 2024, "progid": "SldWorks.Application.32",
            "control": "native COM API", "computer_use": False,
            "model_provider": "independent; credentials belong to the MCP client",
            "com_thread": "single STA", "cross_process_mutex": True,
            "output_root": os.environ["SW_MCP_OUTPUT_ROOT"],
            "validation": "artifacts/acceptance.json; untested tools retain upstream pilot status"}, ensure_ascii=False)

    return engine


if __name__ == "__main__":
    load_server().main()

