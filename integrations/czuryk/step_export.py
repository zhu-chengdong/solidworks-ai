"""Native full-part STEP AP214 export with B-Rep count verification."""
from pathlib import Path
import json


def export_full_step(app,doc,path):
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_export import export_to_step
    if int(get(doc,'GetType'))!=1:
        return {'success':bool(export_to_step(doc,path)),'body_count_verified':False}
    native=str(get(doc,'GetPathName'))
    if not native or Path(get(app.ActiveDoc,'GetPathName')).resolve()!=Path(native).resolve():
        raise RuntimeError('STEP requires the intended saved native document to be active')
    bodies=list(get(doc,'GetBodies2',0,False) or [])
    # Values from the installed SolidWorks 2024 swconst type library.
    before_ap=int(get(app,'GetUserPreferenceIntegerValue',75))
    before_geometry=int(get(app,'GetUserPreferenceIntegerValue',142))
    try:
        if not get(app,'SetUserPreferenceIntegerValue',75,214):raise RuntimeError('Cannot select native STEP AP214')
        if not get(app,'SetUserPreferenceIntegerValue',142,0):raise RuntimeError('Cannot select STEP solid geometry')
        doc.ClearSelection2(True)
        if not export_to_step(doc,str(path)):raise RuntimeError('Native STEP export failed')
    finally:
        get(app,'SetUserPreferenceIntegerValue',75,before_ap)
        get(app,'SetUserPreferenceIntegerValue',142,before_geometry)
    raw=Path(path).read_bytes()
    actual=raw.count(b'MANIFOLD_SOLID_BREP')
    result={'success':actual==len(bodies) and actual>0,'expected_bodies':len(bodies),
        'exported_solid_breps':actual,'body_count_verified':actual==len(bodies),
        'step_ap':214,'color_records':raw.count(b'COLOUR_RGB'),'native_path':native}
    Path(str(path)+'.export.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['success']:raise RuntimeError('STEP solid count differs from the active native part; export not accepted')
    return result
