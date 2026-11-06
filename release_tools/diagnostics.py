"""No credentials, model calls, CAD connection, or geometry changes."""
from __future__ import annotations

from app_runtime import installation_status


async def diagnose():
    import win32cred
    def credential_probe():
        try:
            win32cred.CredRead('ResearchAutomation/SolidWorks/diagnostic/missing-probe', win32cred.CRED_TYPE_GENERIC)
            return {'expected_missing': False}
        except Exception as exc:
            code = getattr(exc, 'winerror', None)
            if code is None and exc.args and isinstance(exc.args[0], int):
                code = exc.args[0]
            return {'expected_missing':code == 1168,'error_type':type(exc).__name__,'code':code}
    vault_before = credential_probe()
    from workbench.engine import mcp_session, mcp_data
    async with mcp_session() as session:
        tools = await session.list_tools()
        health = mcp_data(await session.call_tool("solidworks_health_check", {"params": {}}))
        if health.get('status') != 'ok':
            raise RuntimeError('Packaged MCP health check did not pass')
    # Import native automation modules without creating any COM application.
    from server import load_server
    engine = load_server()
    engine._load_automation_modules()
    from integrations.czuryk.native_only import SOURCE
    import sys
    sys.path.insert(0, str(SOURCE))
    from solidworks_mcp.automation import SolidWorksAutomation
    from integrations.czuryk.reference_build import ReferenceGeometry
    ReferenceGeometry(family='prism', points=[[0,0],[10,0],[0,10]], depth_mm=2)
    from integrations.czuryk.loft_spec import AircraftParameters,resolved_components
    from integrations.czuryk.loft_native import BATCH_SIZE
    aircraft=ReferenceGeometry(family='cartoon_aircraft',depth_mm=1,aircraft=AircraftParameters())
    loft_ready=len(resolved_components(aircraft))==17 and BATCH_SIZE==2
    if not loft_ready:raise RuntimeError('Packaged native loft adapter missing')
    reference_ready = SolidWorksAutomation is not None
    import io,ezdxf,pypdfium2 as pdfium
    from drawing2cad.parser import inspect_dxf,select_spec
    from drawing2cad.native import build_drawing,convert_dwg
    vector=ezdxf.new();vector.units=4;vector.modelspace().add_circle((0,0),10)
    text=io.StringIO();vector.write(text);text.seek(0)
    drawing_ready=len(ezdxf.read(text).modelspace())==1 and all(callable(f) for f in (inspect_dxf,select_spec,build_drawing,convert_dwg))
    pdf=pdfium.PdfDocument.new();page=pdf.new_page(100,100);bitmap=page.render(scale=1)
    try:pdf_ready=bitmap.to_pil().size==(100,100)
    finally:bitmap.close();page.close();pdf.close()
    if not drawing_ready or not pdf_ready:raise RuntimeError('Packaged drawing/PDF runtime failed')
    from drawing2cad.advanced import plan_advanced
    from drawing2cad.native_advanced import create_part,measure
    from drawing2cad.examples import stepped_block
    advanced_ready=all(callable(f) for f in (plan_advanced,create_part,measure)) and len(stepped_block(None).modelspace().query('LEADER'))==5
    if not advanced_ready:raise RuntimeError('Packaged multiview/hole-depth adapter missing')
    from drawing2cad.analytic import plan_analytic
    from drawing2cad.native_analytic import create_part as create_analytic,measure as measure_analytic
    from drawing2cad.examples import analytic_housing
    if not all(callable(f) for f in (plan_analytic,create_analytic,measure_analytic)) or len(analytic_housing(None).modelspace().query('LEADER'))!=4:raise RuntimeError('Packaged analytical silhouette/conical hole adapter missing')
    from engineering.spec import DesignSpec,skill_context
    from engineering.dimensions import DimensionChange,catalog,apply as apply_dimensions,verify as verify_dimensions
    from engineering.finishing import EdgeTreatment,apply as apply_treatments,read as read_treatment
    from engineering.standard_holes import StandardHole,apply as apply_standard_holes,position as read_hole_position
    from engineering.threads import MetricThread,apply as apply_threads,read as read_thread
    from engineering.feature_quality import classify as classify_feature_quality
    from engineering.patterns import HolePattern,apply as apply_patterns,read as read_pattern,geometry as pattern_geometry
    HolePattern(kind='linear',seed_hole_index=0,spacing_mm=20)
    if not all(callable(f) for f in (apply_patterns,read_pattern,pattern_geometry)):raise RuntimeError('Packaged native pattern adapter missing')
    StandardHole(kind='tapped',size='M6',point_mm=[20,10,20],depth_mm=12,thread_representation='modeled',thread_depth_mm=8)
    MetricThread(size='M8',internal=False,point_mm=[0,0,20],length_mm=8)
    if not all(callable(f) for f in (apply_standard_holes,read_hole_position,apply_threads,read_thread,classify_feature_quality)):raise RuntimeError('Packaged native standard/thread adapter missing')
    EdgeTreatment(kind='fillet',target='vertical_edges',size_mm=4,expected_edges=4)
    if not all(callable(f) for f in (apply_treatments,read_treatment)):raise RuntimeError('Packaged edge treatment adapter missing')
    DimensionChange(name='D1@Boss',before_value=8,value=12)
    if not all(callable(f) for f in (catalog,apply_dimensions,verify_dimensions)):raise RuntimeError('Packaged local dimension adapter missing')
    from engineering.native import execute_stage
    from engineering.inspect import inspect_input
    from engineering.validation import mate_readback,verify_assembly_step
    from engineering.package import build_delivery
    from engineering.native_io import save_native_copy,save_native_document
    from engineering.call_lifecycle import wait_for_native_result
    from workbench.native_wait import call_native
    from workbench.cad_inputs import CadStore
    engineering_fixture=DesignSpec(document='part',parts=[{'id':'plate','shape':'plate','length_mm':40,'width_mm':30,'thickness_mm':4}])
    engineering_ready=len(engineering_fixture.stages())==3 and bool(skill_context()['assembly']) and all(callable(f) for f in (execute_stage,inspect_input,CadStore,mate_readback,verify_assembly_step,build_delivery,save_native_copy,save_native_document,wait_for_native_result,call_native))
    if not engineering_ready:raise RuntimeError('Packaged part/assembly adapter missing')
    import uuid
    from workbench.settings import CredentialVault
    vault = CredentialVault()
    probe_url = 'https://diagnostic.invalid/' + uuid.uuid4().hex
    try:
        vault.put('diagnostic', probe_url, 'non-sensitive-credential-storage-test')
        vault_roundtrip = vault.get('diagnostic', probe_url) == 'non-sensitive-credential-storage-test'
        if not vault_roundtrip:
            raise RuntimeError('Packaged credential round-trip failed')
    finally:
        vault.remove('diagnostic', probe_url)
    return {"environment": installation_status(), "tools": len(tools.tools), "health": health,
            "native_modules_imported": True, "reference_compiler_imported": reference_ready,"native_loft_imported":loft_ready,"engineering_imported":engineering_ready,
            "model_called": False, "cad_connected": False,"hole_patterns_imported":True,"standard_holes_and_threads_imported":True,"local_dimension_adapter_imported":True,"drawing_parser_imported":drawing_ready,"advanced_drawing_imported":advanced_ready,"analytic_drawing_imported":True,"pdf_page_rendered":pdf_ready,
            "optional_pdf_review": False, "vault_probe_before":vault_before,"vault_probe_after":credential_probe(),
            "credential_dummy_roundtrip_and_cleanup": vault_roundtrip}
