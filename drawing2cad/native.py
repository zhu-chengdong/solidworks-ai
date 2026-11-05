"""SolidWorks 2024 only: isolated DWG conversion and editable extrusion."""
from __future__ import annotations
import hashlib,json,math,zipfile
from pathlib import Path


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact_paths(task):
    # SW2024 refuses to open a second document with the same base title even
    # when the directories differ. Stable task-specific names avoid that clash.
    suffix=hashlib.sha256(str(Path(task).resolve()).casefold().encode('utf8')).hexdigest()[:12]
    part=Path(task)/('DrawingPart_'+suffix+'.SLDPRT')
    return part,part.with_suffix('.step')


def pinned_source(path,sha256,allowed_root):
    source=Path(path).resolve();root=Path(allowed_root).resolve()
    if (not source.is_relative_to(root) or source.parent.name!='drawings' or source.parent.parent.name!='inputs'
            or source.suffix.lower() not in {'.dwg','.dxf'} or not source.is_file() or source.stat().st_size>20*1024*1024):
        raise ValueError('Only immutable task-pinned drawings are accepted')
    if digest(source)!=sha256:raise ValueError('Input drawing bytes changed')
    return source


def convert_dwg(app,input_path,sha256,output_path,allowed_root):
    import pythoncom,win32com.client
    from scripts.sw_connect import get_com_member as get,create_empty_dispatch_variant
    from scripts.sw_assembly import _activate_model_document
    from solidworks_mcp.automation.com_utils import resolve_solidworks_constant as constant
    source=pinned_source(input_path,sha256,allowed_root);target=Path(output_path).resolve();task=source.parent.parent.parent
    if source.suffix.lower()!='.dwg' or target.parent!=task or target.name!='drawing-converted.dxf' or target.exists():raise ValueError('A new task-local DXF output is required')
    previous=app.ActiveDoc;doc=None
    export_option=constant('swDxfMultiSheetOption');old_export_option=get(app,'GetUserPreferenceIntegerValue',export_option)
    try:
        data=app.GetImportFileData(str(source))
        if data is None:raise RuntimeError('Native DWG import metadata unavailable')
        # Indexed COM property; Invoke preserves its sheet-name argument.
        dispid=data._oleobj_.GetIDsOfNames('ImportMethod')
        data._oleobj_.Invoke(dispid,0,pythoncom.DISPATCH_PROPERTYPUT,0,'',constant('swImportDxfDwg_DoNotImportSheet'))
        data._oleobj_.Invoke(dispid,0,pythoncom.DISPATCH_PROPERTYPUT,0,'Model',constant('swImportDxfDwg_ImportToDrawing'))
        errors=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        doc=app.LoadFile4(str(source),'',data,errors)
        if doc is None or int(get(doc,'GetType'))!=3 or errors.value:raise RuntimeError('Native DWG drawing import failed')
        if not get(doc,'ActivateSheet','Model') or str(get(get(doc,'GetCurrentSheet'),'GetName'))!='Model':raise RuntimeError('DWG model-space sheet could not be activated')
        # swDxfMultiSheet_e: 0 is active-sheet-only, verified against the local
        # SW2024 type library. Never export template/other layout geometry.
        if not get(app,'SetUserPreferenceIntegerValue',export_option,0):raise RuntimeError('Cannot select active-sheet-only DXF export')
        err=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);warn=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        ext=win32com.client.dynamic.DumbDispatch(doc.Extension._oleobj_)
        success=ext.SaveAs3(str(target),0,constant('swSaveAsOptions_Silent'),create_empty_dispatch_variant(),create_empty_dispatch_variant(),err,warn)
        if not success or err.value or not target.is_file() or target.stat().st_size==0:raise RuntimeError('Native DXF conversion export failed')
        if digest(source)!=sha256:raise RuntimeError('Original drawing changed during conversion')
        report={'status':'ok','source_sha256':sha256,'converted_sha256':digest(target),'conversion':'SolidWorks2024 IImportDxfDwgData + LoadFile4 + SaveAs3','selected_space':'Model','active_sheet_only':True,'warnings':warn.value,'output_path':str(target),'computer_use':False}
        target.with_suffix('.conversion.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
    finally:
        get(app,'SetUserPreferenceIntegerValue',export_option,old_export_option)
        if doc is not None:app.CloseDoc(str(get(doc,'GetTitle')))
        if previous is not None:_activate_model_document(app,previous)


def _shift(s,origin):
    return {k:([v[0]-origin[0],v[1]-origin[1]] if k in {'start','end','center'} else v) for k,v in s.items()}


def _measure(automation,doc,spec):
    from scripts.sw_connect import get_com_member as get
    from engineering.native import _exact_bounds
    from .parser import samples
    bodies=automation._get_solid_bodies(doc)
    volume=sum(automation._body_mass_props(b,'mm')['volume_exact'] for b in bodies)
    expected=spec['area_mm2']*spec['thickness_mm'];bounds=_exact_bounds(bodies)
    expected_size=[spec['bounds_mm'][2]-spec['bounds_mm'][0],spec['bounds_mm'][3]-spec['bounds_mm'][1],spec['thickness_mm']]
    sizes_ok=all(math.isclose(a,b,abs_tol=1e-4) for a,b in zip(bounds['size_mm'],expected_size))
    cylinders=[]
    for body in bodies:
        for face in get(body,'GetFaces') or []:
            surface=get(face,'GetSurface')
            if surface is not None and get(surface,'IsCylinder'):
                c=list(get(surface,'CylinderParams'));cylinders.append({'center_mm':[v*1000 for v in c[:3]],'axis':c[3:6],'radius_mm':c[6]*1000})
    origin=[(spec['bounds_mm'][0]+spec['bounds_mm'][2])/2,(spec['bounds_mm'][1]+spec['bounds_mm'][3])/2]
    circles=[s for loop in [spec['outer'],*spec['inner']] for s in loop if s['kind'] in {'circle','arc'}]
    circles_ok=all(any(math.dist(c['center_mm'][:2],[s['center'][0]-origin[0],s['center'][1]-origin[1]])<1e-4 and abs(c['radius_mm']-s['radius'])<1e-4 and abs(abs(c['axis'][2])-1)<1e-6 for c in cylinders) for s in circles)
    passed=len(bodies)==1 and math.isclose(volume,expected,rel_tol=1e-6,abs_tol=1e-4) and sizes_ok and circles_ok
    return {'passed':passed,'body_count':len(bodies),'volume_mm3':volume,'expected_volume_mm3':expected,'exact_bounds':bounds,'expected_size_mm':expected_size,'size_verified':sizes_ok,'circular_profiles_verified':circles_ok,'cylinders':cylinders,'drawing_origin_mm':origin}


def build_drawing(app,spec_path,allowed_root):
    from .parser import inspect_dxf,select_spec,DrawingError
    from integrations.czuryk.native_only import native_automation
    from scripts.sw_connect import get_com_member as get,create_empty_dispatch_variant,open_document
    from scripts.sw_part import sketch,sketch_line,sketch_circle,extrude_boss
    from scripts.sw_sketch_quality import fully_define_sketch,inspect_model_sketches
    from engineering.native_io import save_native_document
    from integrations.czuryk.step_export import export_full_step
    from engineering.previews import export_design_previews
    path=Path(spec_path).resolve();root=Path(allowed_root).resolve();task=path.parent
    if not path.is_relative_to(root) or path.name!='drawing-spec.json' or path.stat().st_size>20000:raise ValueError('A task-local drawing specification is required')
    request=json.loads(path.read_text(encoding='utf-8'));source=pinned_source(task/request['source_file'],request['source_sha256'],allowed_root)
    vector=source
    if source.suffix.lower()=='.dwg':
        vector=task/'drawing-converted.dxf'
        record=json.loads(vector.with_suffix('.conversion.json').read_text(encoding='utf-8'))
        if record['source_sha256']!=request['source_sha256'] or digest(vector)!=record['converted_sha256']:raise ValueError('Converted drawing provenance mismatch')
    inspection=inspect_dxf(vector,request['options'].get('unit_override'),advanced=request['options'].get('advanced',False))
    spec,question=select_spec(inspection,request['options'])
    if question:raise DrawingError(question)
    # A durable reservation prevents retrying a write accepted before a timeout.
    marker=task/'drawing-native-started.json'
    with marker.open('x',encoding='utf-8') as stream:json.dump({'source_sha256':request['source_sha256'],'view':spec['id']},stream)
    output,step_path=artifact_paths(task)
    if output.exists():raise ValueError('Existing native model cannot be replaced')
    automation=native_automation(app)
    if spec.get('kind') in {'orthographic','profile_holes'}:
        from .native_advanced import build
        return build(app,automation,spec,task,source,request['source_sha256'])
    made=automation.create_new_part()
    if not made.get('success'):raise RuntimeError('Native part creation failed')
    doc=app.ActiveDoc;origin=[(spec['bounds_mm'][0]+spec['bounds_mm'][2])/2,(spec['bounds_mm'][1]+spec['bounds_mm'][3])/2]
    with sketch(doc,'Front Plane') as ref:
        manager=doc.SketchManager;before=get(manager,'AddToDB')
        loops=[]
        try:
            manager.AddToDB=True
            for loop in [spec['outer'],*spec['inner']]:
                entities=[]
                for original in loop:
                    s=_shift(original,origin)
                    if s['kind']=='line':entity=sketch_line(doc,*[v/1000 for v in s['start']],*[v/1000 for v in s['end']])
                    elif s['kind']=='circle':entity=sketch_circle(doc,*[v/1000 for v in s['center']],s['radius']/1000)
                    else:
                        entity=manager.CreateArc(s['center'][0]/1000,s['center'][1]/1000,0.,s['start'][0]/1000,s['start'][1]/1000,0.,s['end'][0]/1000,s['end'][1]/1000,0.,1 if s['ccw'] else -1)
                    if entity is None:raise RuntimeError('Native drawing entity creation failed')
                    entities.append((entity,s))
                loops.append(entities)
        finally:manager.AddToDB=before
        def relation(objects,name):
            doc.ClearSelection2(True)
            for obj in objects:
                if not obj.Select4(True,create_empty_dispatch_variant()):raise RuntimeError('Cannot select native drawing entity')
            get(doc,'SketchAddConstraints',name);doc.ClearSelection2(True)
        for loop in loops:
            if loop[0][1]['kind']=='circle':continue
            for i,(entity,s) in enumerate(loop):
                relation([get(entity,'GetEndPoint2'),get(loop[(i+1)%len(loop)][0],'GetStartPoint2')],'sgCOINCIDENT')
                if s['kind']=='line':
                    if abs(s['start'][0]-s['end'][0])<1e-9:relation([entity],'sgVERTICAL')
                    elif abs(s['start'][1]-s['end'][1])<1e-9:relation([entity],'sgHORIZONTAL')
        with automation.dimension_input_guard():initial=fully_define_sketch(doc)
    feature=extrude_boss(doc,ref,spec['thickness_mm']/1000,direction=False)
    if feature is None:raise RuntimeError('Native drawing extrusion failed')
    feature.Name='DrawingExtrusion'
    if not get(doc,'EditRebuild3'):raise RuntimeError('Native rebuild failed')
    quality=inspect_model_sketches(doc)
    if quality['status']!='pass':raise RuntimeError('Native sketch editability check failed')
    measured=_measure(automation,doc,spec)
    if not measured['passed']:raise RuntimeError('Native geometry differs from drawing coordinates')
    save_native_document(app,doc,output)
    app.CloseDoc(str(get(doc,'GetTitle')))
    doc=open_document(app,str(output),read_only=False,silent=True,raise_on_error=True)
    reopened=_measure(automation,doc,spec);reopened_quality=inspect_model_sketches(doc)
    if not reopened['passed'] or reopened_quality['status']!='pass':raise RuntimeError('Saved/reopened model failed geometry or editability readback')
    step=export_full_step(app,doc,step_path)
    from solidworks_mcp.automation.com_utils import resolve_solidworks_constant as constant
    hide=constant('swViewDisplayHideAllTypes');option=constant('swDetailingNoOptionSpecified')
    old=doc.Extension.GetUserPreferenceToggle(hide,option)
    try:
        doc.Extension.SetUserPreferenceToggle(hide,option,True)
        if not doc.Extension.GetUserPreferenceToggle(hide,option):raise RuntimeError('Cannot hide construction annotations in preview')
        previews=export_design_previews(automation,doc,task)
    finally:doc.Extension.SetUserPreferenceToggle(hide,option,old)
    if digest(source)!=request['source_sha256']:raise RuntimeError('Original drawing changed')
    report={'status':'ok','success':True,'document':{'title':str(get(doc,'GetTitle')),'path':str(output),'type':1},'geometry':measured,'saved_reopened_geometry':reopened,'sketch_quality':reopened_quality,'initial_sketch_quality':initial,'source_sha256':request['source_sha256'],'source_unchanged':True,'selected_view':spec['id'],'dimension_policy':spec['dimension_policy'],'step':step,'previews':previews,'native_only_audit':automation.native_only_audit,'paid_model_calls':0}
    (task/'drawing-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    files=[output,step_path,task/'drawing-acceptance.json',task/'drawing-inspection.json',task/'drawing-contours.png',task/'preview-manifest.json']+[task/v['file'] for v in previews['views']]
    files=[p for p in files if p.is_file()]
    (task/'SHA256SUMS-drawing.txt').write_text('\n'.join(digest(p)+'  '+p.relative_to(task).as_posix() for p in files)+'\n',encoding='utf-8')
    package=task/'Drawing_delivery.zip'
    with zipfile.ZipFile(package,'x',zipfile.ZIP_DEFLATED) as archive:
        for p in [*files,task/'SHA256SUMS-drawing.txt']:archive.write(p,p.relative_to(task).as_posix())
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:raise RuntimeError('Drawing package integrity failed')
    return report
