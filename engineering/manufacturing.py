"""Native 2024 drawing adapter. No UI, macros, or synthetic dimension text."""
from __future__ import annotations
import hashlib, json, math, os
from pathlib import Path
from .manufacturing_spec import ManufacturingRequest, STAGES


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')


def get(obj, name, *args):
    from scripts.sw_connect import get_com_member
    return get_com_member(obj, name, *args)


def typed(obj, interface):
    from solidworks_mcp.automation.com_utils import typed as cast
    return cast(obj, interface)


def views(doc):
    return list(get(get(doc,'GetCurrentSheet'),'GetViews') or [])


def view_name(view): return str(get(view,'GetName2'))


def transform(view, point):
    data=list(get(get(view,'ModelToViewTransform'),'ArrayData'))
    return [data[12]*sum(data[c*3+r]*point[c] for c in range(3))+data[9+r] for r in range(3)]


def resolve_standard_names(names,named_rotation,standard_rotation):
    """Match actual drawing-view rotations to the model's standard rotations."""
    rotations={}
    for name in names:
        try:
            value=named_rotation(name)
            if value is not None and len(value)>=9:rotations[str(name)]=[float(v) for v in value[:9]]
        except Exception:continue
    result={}
    # Official swStandardViews_e, checked in the installed 2024 type library.
    for semantic,identifier in [('front',1),('top',5),('left',3)]:
        target=[float(v) for v in list(standard_rotation(identifier))[:9]]
        matches=[name for name,value in rotations.items() if len(target)==9 and max(abs(a-b) for a,b in zip(target,value))<1e-6]
        if len(matches)!=1:raise ValueError('Cannot uniquely resolve the native standard view: '+semantic)
        result[semantic]=matches[0]
    return result


def evidence_view(view):
    return {'name':view_name(view),'type':int(get(view,'Type')),
        'orientation':str(get(view,'GetOrientationName')),
        'position_m':list(get(view,'Position')),'scale':list(get(view,'ScaleRatio')),
        'outline_m':list(get(view,'GetOutline')),
        'model_to_sheet':list(get(get(view,'ModelToViewTransform'),'ArrayData'))}


def collect_entities(view, kind):
    result=[]
    for component in get(view,'GetVisibleComponents') or []:
        result.extend(get(view,'GetVisibleEntities2',component,kind) or [])
    return result


def inspect_entities(view):
    vertices=[];circles=[];lines=[]
    for vertex in collect_entities(view,2):
        point=list(get(vertex,'GetPoint'))
        # Drawing-context vertices include a native view offset, unlike curve
        # parameters. They are only sorting references, not source-model points.
        vertices.append({'native_drawing_context_mm':[v*1000 for v in point]})
    for edge in collect_entities(view,1):
        curve=get(edge,'GetCurve')
        if get(curve,'IsCircle'):
            cp=list(get(curve,'CircleParams'))
            circles.append({'center_mm':[v*1000 for v in cp[:3]],'axis':cp[3:6],
                'radius_mm':cp[6]*1000,'sheet_center_m':transform(view,cp[:3])})
        elif get(curve,'IsLine'):
            a=get(edge,'GetStartVertex');b=get(edge,'GetEndVertex')
            if a is not None and b is not None:lines.append([list(get(a,'GetPoint')),list(get(b,'GetPoint'))])
    return {'vertices':vertices,'circles':circles,'lines_count':len(lines)}


def _prepare(app,out,spec,request,record,stamp):
    from scripts.sw_connect import new_document
    from .native_open import open_native_document as open_document
    from .native_io import save_native_document
    from .native import _exact_bounds
    model_path=out/('model_'+stamp+'.SLDPRT')
    with model_path.open('xb') as target:target.write(Path(spec['source']['path']).read_bytes())
    model=open_document(app,str(model_path),read_only=True,silent=True,raise_on_error=True)
    if int(get(model,'GetType'))!=1:raise ValueError('Manufacturing drawings currently require a single native part')
    bodies=list(get(model,'GetBodies2',0,False) or [])
    if len(bodies)!=1:raise ValueError('This drawing route requires exactly one solid body')
    from integrations.czuryk.native_only import native_automation
    volume_mm3=native_automation(app)._body_mass_props(bodies[0],'mm')['volume_exact']
    bounds=_exact_bounds(bodies);sizes=bounds['size_mm']
    scale=request.scale or next((s for s in (2.,1.,.5,.2,.1,.05) if sizes[0]*s<=115 and sizes[1]*s<=75 and sizes[2]*s<=55),None)
    if scale is None or sizes[0]*scale>115 or sizes[1]*scale>75 or sizes[2]*scale>55:
        raise ValueError('The requested scale does not fit the bounded A3 layout')
    installed=Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'))/'SOLIDWORKS'/'SOLIDWORKS 2024'/'templates'/'gb_a3.drwdot'
    standard_rotations={i:get(model,'GetStandardViewRotation',i) for i in (1,5,3)}
    doc=new_document(app,'drawing',template_path=str(installed) if installed.is_file() else None);drawing=typed(doc,'IDrawingDoc')
    sheet=get(drawing,'GetCurrentSheet');name=str(get(sheet,'GetName'))
    # Official swconst 2024: A3=8, TemplateNone=13. The upstream paper-size
    # numbers are not used. Keep the installed template's real sheet format.
    props=list(get(sheet,'GetProperties2'))
    sheet.SetProperties2(8,int(props[1]),scale,1.,True,.420,.297,True)
    actual=list(get(sheet,'GetProperties2'))
    if int(actual[0])!=8 or not bool(actual[4]) or abs(actual[5]-.420)>1e-6 or abs(actual[6]-.297)>1e-6:
        raise RuntimeError('Native A3 first-angle sheet readback failed')
    path=out/('drawing_'+stamp+'.SLDDRW');save_native_document(app,doc,path)
    centers={'front':(.160,.205),'top':(.160,.085),'left':(.320,.205)}
    if not drawing.Create1stAngleViews2(str(model_path)):raise RuntimeError('Native first-angle three-view creation failed')
    get(doc,'ForceRebuild3',False)
    actual_views={view_name(v):typed(v,'IView') for v in views(drawing)}
    rotations={name:list(get(get(v,'ModelToViewTransform'),'ArrayData'))[:9] for name,v in actual_views.items()}
    write_json(out/'native-view-rotations.json',{'drawing_views':rotations,'standard':standard_rotations})
    native_names=resolve_standard_names(list(actual_views),lambda name:rotations[name],lambda index:standard_rotations[index])
    created={}
    import pythoncom,win32com.client
    for semantic,name in native_names.items():
        view=actual_views[name];view.PositionLocked=False;view.ScaleRatio=(scale,1.)
        view.Position=win32com.client.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,centers[semantic])
        created[semantic]=evidence_view(view)
    get(doc,'ForceRebuild3',False)
    title_notes=[]
    sheet_view=get(drawing,'GetFirstView')
    for note in get(sheet_view,'GetNotes') or []:
        linked=str(get(note,'PropertyLinkedText'))
        replacement=request.title if linked=='$PRPSHEET:"名称"' else ('DWG-'+stamp[:8] if linked=='$PRPSHEET:"代号"' else None)
        if replacement is not None:
            if not note.SetText(replacement) or str(get(note,'GetText'))!=replacement:raise RuntimeError('Native title-block field readback failed')
            title_notes.append({'text':replacement,'replaces_link':linked})
    save_native_document(app,doc)
    record.update(drawing_path=str(path),model_path=str(model_path),model_sha256=digest(model_path),
        bounds=bounds,volume_mm3=volume_mm3,scale=scale,sheet_properties=actual,views=created,native_view_names=native_names,title_notes=title_notes,
        entity_probe={name:inspect_entities(next(v for v in views(drawing) if view_name(v)==row['name'])) for name,row in created.items()})


def drawing_document(app,record):
    from .native_open import open_native_document as open_document
    from scripts.sw_assembly import _activate_model_document
    doc=open_document(app,record['drawing_path'],silent=True,raise_on_error=True)
    if int(get(doc,'GetType'))!=3 or Path(get(doc,'GetPathName')).resolve()!=Path(record['drawing_path']).resolve():
        raise RuntimeError('Native drawing identity changed')
    _activate_model_document(app,doc)
    return doc,typed(doc,'IDrawingDoc')


def select_entities(doc,drawing,view,entities):
    doc.ClearSelection2(True)
    if not drawing.ActivateView(view_name(view)):raise RuntimeError('Cannot activate the native drawing view')
    selection=get(get(doc,'SelectionManager'),'CreateSelectData');selection.View=view
    for index,entity in enumerate(entities):
        if not typed(entity,'IEntity').Select4(index>0,selection):raise RuntimeError('Cannot select the native drawing reference')


def dimension_evidence(value):
    display=typed(value,'IDisplayDimension');annotation=get(display,'GetAnnotation')
    dimension=get(display,'GetDimension2',0)
    result={'name':str(get(dimension,'FullName')),'annotation':str(get(annotation,'GetName')),
        'value_m':float(get(dimension,'SystemValue')),'position_m':list(get(annotation,'GetPosition')),
        'is_hole_callout':bool(get(display,'IsHoleCallout')),
        'attached_entity_count':len(get(annotation,'GetAttachedEntities3') or []),
        'text_parts':[str(get(display,'GetText',i)) for i in range(5)]}
    return result


def center_arc_endpoints(value):
    """Change the native reference condition, never the measured dimension value."""
    dimension=get(typed(value,'IDisplayDimension'),'GetDimension2',0)
    result=[]
    for index in (1,2):
        condition=int(get(dimension,'GetArcEndCondition',index))
        if condition in (1,2,3):
            if condition!=1 and int(get(dimension,'SetArcEndCondition',index,1))!=0:
                raise RuntimeError('Cannot use the actual circular center for the hole-position dimension')
            if int(get(dimension,'GetArcEndCondition',index))!=1:raise RuntimeError('Native arc-center condition readback failed')
            condition=1
        result.append(condition)
    if 1 not in result:raise RuntimeError('The hole-position dimension did not reference a circular entity')
    return result


def add_linear(doc,drawing,view,entities,axis,position,expected_mm,identity):
    select_entities(doc,drawing,view,entities)
    method=getattr(doc,'AddHorizontalDimension2' if axis==0 else 'AddVerticalDimension2')
    value=method(*position,0.)
    if value is None:raise RuntimeError('Native dimension creation failed: '+identity)
    arc_conditions=center_arc_endpoints(value) if identity.startswith('hole_') else None
    display=typed(value,'IDisplayDimension')
    # Keep explicit sheet placement independent of document centering settings.
    display.CenterText=False
    if bool(get(display,'CenterText')):raise RuntimeError('Cannot disable automatic dimension text centering')
    annotation=get(display,'GetAnnotation')
    if not get(annotation,'SetPosition2',*position,0.):raise RuntimeError('Cannot set the native dimension text position')
    result=dimension_evidence(value)
    if max(abs(a-b) for a,b in zip(result['position_m'][:2],position))>1e-6:
        raise RuntimeError('Native dimension text placement readback failed: '+identity)
    if not math.isclose(result['value_m']*1000,expected_mm,abs_tol=.002) or result['attached_entity_count']<1:
        raise RuntimeError('Actual associated dimension does not match measured geometry: '+identity+' '+str(result))
    result.update(id=identity,expected_mm=expected_mm,view=view_name(view),kind='linear')
    if arc_conditions is not None:result['arc_end_conditions']=arc_conditions
    return result


def extreme_vertices(view,axis):
    vertices=collect_entities(view,2)
    if len(vertices)<2:raise ValueError('Visible native vertex references are required for these dimensions')
    points=[transform(view,get(v,'GetPoint')) for v in vertices]
    # Stable orthogonal choice keeps extension lines on a common outside edge.
    low=min(range(len(vertices)),key=lambda i:(round(points[i][axis],8),round(points[i][1-axis],8)))
    high=max(range(len(vertices)),key=lambda i:(round(points[i][axis],8),-round(points[i][1-axis],8)))
    if abs(points[high][axis]-points[low][axis])<1e-8:raise ValueError('Degenerate projected dimension')
    return [vertices[low],vertices[high]],points[low],points[high]


def hole_edges(view,bounds):
    """Only real circular rims on the highest +Z planar entry are qualified."""
    groups={};z=bounds['max'][2]
    for edge in collect_entities(view,1):
        curve=get(edge,'GetCurve')
        if not get(curve,'IsCircle'):continue
        cp=list(get(curve,'CircleParams'))
        if abs(cp[5])<1-1e-6 or abs(cp[2]*1000-z)>.002:continue
        # Concavity is checked on the adjacent inward-facing cylindrical wall;
        # an external boss or circular outside perimeter is never a hole.
        internal=False
        for face in get(edge,'GetTwoAdjacentFaces2') or []:
            if face is None:continue
            surface=get(face,'GetSurface')
            if surface is not None and get(surface,'IsCylinder') and bool(get(face,'FaceInSurfaceSense')):
                internal=True
        if not internal:continue
        key=(round(cp[0]*1000,4),round(cp[1]*1000,4))
        row={'edge':edge,'center_mm':[v*1000 for v in cp[:3]],'radius_mm':cp[6]*1000,'sheet_center_m':transform(view,cp[:3])}
        if key not in groups or groups[key]['radius_mm']<row['radius_mm']:groups[key]=row
    if len(groups)>8:raise ValueError('This A3 callout layout supports at most eight distinct top-entry holes')
    return [groups[k] for k in sorted(groups)]


def validate_hole_scope(doc,holes):
    """Never silently omit full cylindrical side/bottom-entry holes."""
    entries=[h['center_mm'][:2] for h in holes]
    for body in get(doc,'GetBodies2',0,False) or []:
        for face in get(body,'GetFaces') or []:
            surface=get(face,'GetSurface')
            if surface is None or not get(surface,'IsCylinder') or not bool(get(face,'FaceInSurfaceSense')):continue
            uv=list(get(face,'GetUVBounds'))
            if abs(abs(uv[1]-uv[0])-2*math.pi)>1e-5:continue
            cp=list(get(surface,'CylinderParams'))
            if abs(cp[5])<1-1e-6 or not any(math.dist([cp[0]*1000,cp[1]*1000],xy)<.002 for xy in entries):
                raise ValueError('Side/bottom-entry cylindrical holes require a separately qualified drawing route; no incomplete hole drawing exported')


def callout_variables(display,document_path,app):
    from .manufacturing_callouts import read_variables
    return read_variables(app,document_path,list(get(display,'GetHoleCalloutVariables') or []))


def _annotate(app,out,request,record):
    from .native_io import save_native_document
    from integrations.czuryk.native_only import native_automation
    doc,drawing=drawing_document(app,record);actual={view_name(v):v for v in views(drawing)}
    front=actual[record['views']['front']['name']];side=actual[record['views']['left']['name']]
    from .manufacturing_layout import callout_anchor,free_text_coordinate
    dimensions=[];holes=hole_edges(front,record['bounds']);guard=native_automation(app);occupied=[]
    if request.hole_positions or request.hole_callouts:
        model=get(front,'ReferencedDocument')
        if model is None:raise RuntimeError('The actual referenced part is unavailable for hole coverage checks')
        validate_hole_scope(model,holes)
    with guard.dimension_input_guard():
        minimum=transform(front,[v/1000 for v in record['bounds']['min']])
        maximum=transform(front,[v/1000 for v in record['bounds']['max']])
        if request.dimensions:
            for axis,identity,size in [(0,'overall_x',record['bounds']['size_mm'][0]),(1,'overall_y',record['bounds']['size_mm'][1])]:
                refs,lo,hi=extreme_vertices(front,axis);outline=list(get(front,'GetOutline'))
                center=list(get(front,'Position'))
                extensions=[h['sheet_center_m'][axis] for h in holes] if request.hole_positions else []
                coordinate=free_text_coordinate(center[axis],minimum[axis],maximum[axis],extensions)
                pos=[coordinate,outline[1]-.018] if axis==0 else [outline[0]-.018,coordinate]
                dimensions.append(add_linear(doc,drawing,front,refs,axis,pos,size,identity))
            refs,lo,hi=extreme_vertices(side,0);outline=list(get(side,'GetOutline'))
            dimensions.append(add_linear(doc,drawing,side,refs,0,[list(get(side,'Position'))[0],outline[1]-.018],record['bounds']['size_mm'][2],'overall_z'))
        low_x=extreme_vertices(front,0)[0][0];low_y=extreme_vertices(front,1)[0][0]
        for index,hole in enumerate(holes):
            if request.hole_positions:
                outline=list(get(front,'GetOutline'));point=hole['sheet_center_m']
                for axis,vertex,identity in [(0,low_x,'hole_x'),(1,low_y,'hole_y')]:
                    expected=hole['center_mm'][axis]-record['bounds']['min'][axis]
                    if expected<.002:continue
                    middle=(minimum[axis]+point[axis])/2
                    pos=[middle,outline[1]-.030-index*.011] if axis==0 else [outline[0]-.030-index*.011,middle]
                    dimensions.append(add_linear(doc,drawing,front,[hole['edge'],vertex],axis,pos,expected,f'{identity}_{index+1}'))
            if request.hole_callouts:
                select_entities(doc,drawing,front,[hole['edge']])
                outline=list(get(front,'GetOutline'));pos=callout_anchor(hole,holes,outline,occupied,index,record['scale'])
                value=drawing.AddHoleCallout2(*pos,0.)
                if value is None:raise RuntimeError('Native hole callout creation failed')
                display=typed(value,'IDisplayDimension');evidence=dimension_evidence(display)
                variables=callout_variables(display,record['drawing_path'],app)
                if not evidence['is_hole_callout'] or not variables or evidence['attached_entity_count']<1:
                    raise RuntimeError('A genuine associated hole callout was not returned')
                evidence.update(id=f'hole_callout_{index+1}',kind='hole_callout',view=view_name(front),variables=variables,
                    center_mm=hole['center_mm'],rim_radius_mm=hole['radius_mm'],planned_layout=occupied[-1])
                dimensions.append(evidence)
    record.update(dimensions=dimensions,holes=[{k:v for k,v in h.items() if k!='edge'} for h in holes])
    doc.ClearSelection2(True);get(doc,'ForceRebuild3',False);save_native_document(app,doc)


def affine(data,point):
    data=list(data)
    return [data[12]*sum(data[c*3+r]*point[c] for c in range(3))+data[9+r] for r in range(3)]


def section_evidence(view):
    section=get(view,'GetSection')
    if section is None or int(get(view,'Type'))!=2:raise RuntimeError('The generated view is not a genuine native section')
    section=typed(section,'IDrSection');parent=get(section,'GetView');cut=get(section,'GetSectionView')
    result={'view':evidence_view(view),'label':str(get(section,'GetLabel')),
        'line_info':list(get(section,'GetLineInfo') or []),'arrow_info':list(get(section,'GetArrowInfo') or []),
        'auto_hatch':bool(get(section,'GetAutoHatch')),
        'parent_view':view_name(parent),'section_view':view_name(cut),
        'face_hatch_count':int(get(view,'GetFaceHatchCount'))}
    if not result['line_info'] or len(result['arrow_info'])!=12 or view_name(cut)!=view_name(view):
        raise RuntimeError('Native section relation or cut-line readback failed')
    if result['face_hatch_count']<1:raise RuntimeError('The section has no actual native hatched material face')
    return result


def _section(app,out,request,record):
    from scripts.sw_connect import create_empty_dispatch_variant
    from .native_io import save_native_document
    import pythoncom
    doc,drawing=drawing_document(app,record)
    if request.section is None:record['section']=None;return
    front=next(v for v in views(drawing) if view_name(v)==record['views']['front']['name'])
    axis='xy'.index(request.section.axis);other=1-axis;bounds=record['bounds']
    at=request.section.at_mm
    if at is None:
        holes=record.get('holes',[])
        at=holes[len(holes)//2]['center_mm'][other] if holes else (bounds['min'][other]+bounds['max'][other])/2
    if not bounds['min'][other]+.001<at<bounds['max'][other]-.001:raise ValueError('Section cut must pass strictly inside the part envelope')
    p0=[0.,0.,bounds['max'][2]];p1=list(p0)
    p0[axis]=bounds['min'][axis]-10/record['scale'];p1[axis]=bounds['max'][axis]+10/record['scale'];p0[other]=p1[other]=at
    sheet_points=[transform(front,[v/1000 for v in point]) for point in (p0,p1)]
    sheet_points=[[p[0],p[1],0.] for p in sheet_points]
    doc.ClearSelection2(True)
    if not drawing.ActivateView(view_name(front)):raise RuntimeError('Cannot activate the section parent view')
    manager=get(doc,'SketchManager');manager.InsertSketch(True)
    sketch=get(doc,'GetActiveSketch2')
    if sketch is None:raise RuntimeError('Native section-line sketch was not entered')
    data=list(get(get(sketch,'ModelToSketchTransform'),'ArrayData'))
    a,b=[affine(data,point) for point in sheet_points]
    segment=manager.CreateLine(*a,*b)
    if segment is None:raise RuntimeError('Native section cutting line could not be created')
    manager.InsertSketch(True);doc.ClearSelection2(True)
    if not segment.Select4(False,create_empty_dispatch_variant()):raise RuntimeError('Native section cutting line could not be selected')
    view=drawing.CreateSectionViewAt5(.320,.100,0.,request.section.label,1,pythoncom.Empty,0.)
    if view is None:raise RuntimeError('Native full section creation failed')
    view=typed(view,'IView');view.ScaleRatio=(record['scale'],1.)
    doc.ClearSelection2(True);get(doc,'ForceRebuild3',False)
    actual=section_evidence(view)
    if actual['parent_view']!=view_name(front) or actual['label']!=request.section.label:
        raise RuntimeError('The native section does not reference the requested parent/label')
    starts=[actual['arrow_info'][:3],actual['arrow_info'][6:9]]
    direct=max(math.dist(a,b) for a,b in zip(starts,sheet_points))
    reverse=max(math.dist(a,b) for a,b in zip(starts,reversed(sheet_points)))
    if min(direct,reverse)>1e-6:raise RuntimeError('The actual native section line does not match the requested cut')
    actual['cut_position_verified']=True
    record['section']={**actual,'model_line_mm':[p0,p1],'sheet_line_m':sheet_points,'axis':request.section.axis,'at_mm':at}
    save_native_document(app,doc)


def drawing_dimensions(drawing,document_path,app):
    result=[]
    for view in views(drawing):
        dimensions=list(get(view,'GetDisplayDimensions') or []);seen=set()
        if len(dimensions)!=int(get(view,'GetDisplayDimensionCount')) or len(dimensions)>128:
            raise RuntimeError('Native dimension enumeration is incomplete or exceeds the bounded limit')
        for current in dimensions:
            item=dimension_evidence(current)
            if item['name'] in seen:raise RuntimeError('Native dimension enumeration cycled')
            seen.add(item['name']);item['view']=view_name(view)
            if item['is_hole_callout']:item['variables']=callout_variables(typed(current,'IDisplayDimension'),document_path,app)
            result.append(item)
    return result


def sheet_notes(drawing):
    sheet_view=get(drawing,'GetFirstView')
    return [{'text':str(get(note,'GetText')),'linked':str(get(note,'PropertyLinkedText'))}
        for note in get(sheet_view,'GetNotes') or []]


def inspect_existing(app,spec_path,allowed_root):
    from .native_open import open_native_document as open_document
    from scripts.sw_assembly import _activate_model_document
    source=Path(spec_path).resolve();root=Path(allowed_root).resolve();out=source.parent
    if source.name!='manufacturing-spec.json' or not out.is_relative_to(root):raise ValueError('Invalid drawing task')
    record=json.loads((out/'manufacturing-progress.json').read_text(encoding='utf8'))
    path=Path(record['drawing_path']).resolve()
    if path.parent!=out or path.suffix.lower()!='.slddrw':raise ValueError('Drawing identity left the task directory')
    previous=app.ActiveDoc;existing=app.GetOpenDocumentByName(str(path));doc=None
    try:
        doc=open_document(app,str(path),read_only=True,silent=True,raise_on_error=True);drawing=typed(doc,'IDrawingDoc')
        return {'status':'ok','read_only':True,'views':[evidence_view(v) for v in views(drawing)],
            'sheet_notes':sheet_notes(drawing),
            'dimensions':drawing_dimensions(drawing,path,app),'sections':[section_evidence(v) for v in views(drawing) if int(get(v,'Type'))==2]}
    finally:
        if doc is not None and existing is None:app.CloseDoc(str(get(doc,'GetTitle')))
        if previous is not None:_activate_model_document(app,previous)


def _deliver(app,out,request,record,stamp):
    from scripts.sw_connect import create_empty_dispatch_variant
    from .native_open import open_native_document as open_document
    from .native_io import save_native_document
    from .manufacturing_pdf import inspect_pdf
    import pythoncom,win32com.client,zipfile
    doc,drawing=drawing_document(app,record);save_native_document(app,doc)
    app.CloseDoc(str(get(doc,'GetTitle')))
    doc=open_document(app,record['drawing_path'],silent=True,raise_on_error=True);drawing=typed(doc,'IDrawingDoc')
    actual_views={view_name(v):v for v in views(drawing)}
    for semantic,expected in record['views'].items():
        view=actual_views.get(expected['name'])
        if view is None:raise RuntimeError('A standard view was lost after native reopen')
        actual=evidence_view(view)
        if max(abs(a-b) for a,b in zip(actual['model_to_sheet'][:9],expected['model_to_sheet'][:9]))>1e-6:
            raise RuntimeError('Native reopened view orientation changed: '+semantic)
        if max(abs(a-b) for a,b in zip(actual['position_m'],expected['position_m']))>1e-5:
            raise RuntimeError('Native reopened view placement changed: '+semantic)
        if Path(get(view,'GetReferencedModelName')).resolve()!=Path(record['model_path']).resolve():
            raise RuntimeError('Drawing view model reference changed')
    actual_dimensions={d['name']:d for d in drawing_dimensions(drawing,record['drawing_path'],app)}
    reopened_notes=sheet_notes(drawing)
    if any(not any(n['text']==expected['text'] for n in reopened_notes) for expected in record.get('title_notes',[])):
        raise RuntimeError('The native title block changed after reopening')
    checked=[]
    for expected in record.get('dimensions',[]):
        item=actual_dimensions.get(expected['name'])
        if item is None or not math.isclose(item['value_m'],expected['value_m'],abs_tol=2e-6):
            raise RuntimeError('A native associated dimension was lost or changed after reopening')
        if item['is_hole_callout']!=expected['is_hole_callout'] or item['attached_entity_count']<1:
            raise RuntimeError('A reopened native dimension lost its reference or callout identity')
        if expected['is_hole_callout'] and item['variables']!=expected['variables']:
            raise RuntimeError('Native hole specification variables changed after reopening')
        if max(abs(a-b) for a,b in zip(item['position_m'][:2],expected['position_m'][:2]))>1e-5:
            raise RuntimeError('Native dimension text moved after reopening: '+expected['id'])
        checked.append({**expected,**item,'save_reopen_verified':True})
    section=None
    if request.section is not None:
        section=section_evidence(actual_views[record['section']['section_view']])
        old_line=record['section']['line_info'];new_line=section['line_info']
        if section['parent_view']!=record['section']['parent_view'] or len(old_line)!=len(new_line) or max(abs(a-b) for a,b in zip(old_line,new_line))>1e-7:
            raise RuntimeError('Native section cut changed after reopening')
        starts=[section['arrow_info'][:3],section['arrow_info'][6:9]];intended=record['section']['sheet_line_m']
        if min(max(math.dist(a,b) for a,b in zip(starts,intended)),max(math.dist(a,b) for a,b in zip(starts,reversed(intended))))>1e-6:
            raise RuntimeError('Reopened native section cut position does not match its intent')
        section.update(cut_position_verified=True,axis=record['section']['axis'],at_mm=record['section']['at_mm'])
    sheet_properties=list(get(get(drawing,'GetCurrentSheet'),'GetProperties2'))
    if not sheet_properties[4] or int(sheet_properties[0])!=8:raise RuntimeError('Drawing sheet projection or A3 size changed')
    pdf=out/('drawing_'+stamp+'.pdf');preview=out/'manufacturing-preview.png'
    export=typed(get(app,'GetExportFileData',1),'IExportPdfData')
    export.ViewPdfAfterSaving=False
    export.ExportAs3D=False
    names=list(get(drawing,'GetSheetNames') or [])
    if len(names)!=1:raise ValueError('This drawing route exports one explicitly identified sheet')
    # Official: specified=3, with the actual names in a BSTR SAFEARRAY.
    sheets=win32com.client.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BSTR,names)
    if not export.SetSheets(3,sheets):raise RuntimeError('Native PDF sheet selection failed for the explicit sheet name')
    if int(get(export,'GetWhichSheets'))!=3 or list(get(export,'GetSheets') or [])!=names:
        raise RuntimeError('Native PDF sheet selection readback failed')
    errors=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    warnings=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    if not doc.Extension.SaveAs(str(pdf),0,1,export,errors,warnings) or errors.value or not pdf.is_file():
        raise RuntimeError('Native PDF export failed')
    if Path(get(doc,'GetPathName')).resolve()!=Path(record['drawing_path']).resolve():raise RuntimeError('PDF export changed the native document identity')
    pdf_proof=inspect_pdf(pdf,checked,preview)
    if digest(record['model_path'])!=record['model_sha256']:raise RuntimeError('Referenced part bytes changed')
    proof={'status':'passed','passed':True,'native_api_only':True,'solidworks_revision':str(get(app,'RevisionNumber')),
        'drawing':Path(record['drawing_path']).name,'model':Path(record['model_path']).name,'pdf':pdf.name,
        'projection':'first_angle','standard_views':record['views'],'title_notes':record.get('title_notes',[]),'source_model_preserved':True,
        'save_reopen_verified':True,'volume_mm3':record.get('volume_mm3'),'dimensions':checked,'section':section,'pdf_review':pdf_proof,
        'preview':'manufacturing-preview.png','nominal_geometry_only':True,'warnings':[],
        'qualification_scope':'Single-part A3 first-angle front/top/left, associated nominal dimensions, straight full section and real top-entry hole callouts; manufacturing tolerances remain explicit user design inputs.'}
    acceptance=out/'manufacturing-acceptance.json';write_json(acceptance,proof)
    files=[Path(record['drawing_path']),Path(record['model_path']),pdf,preview,acceptance]
    manifest={p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in files}
    hashes=out/'manufacturing-sha256.json';write_json(hashes,manifest)
    package=out/('manufacturing-package_'+stamp+'.zip')
    with zipfile.ZipFile(package,'x',zipfile.ZIP_DEFLATED) as zipped:
        for file in files+[hashes]:zipped.write(file,file.name)
    with zipfile.ZipFile(package) as zipped:
        if zipped.testzip() is not None or any(hashlib.sha256(zipped.read(name)).hexdigest()!=item['sha256'] for name,item in manifest.items()):
            raise RuntimeError('Drawing dependency ZIP verification failed')
    record.update(acceptance=str(acceptance),preview=str(preview),pdf=str(pdf),package=str(package),verification=proof,
        package_verified=True,package_sha256=digest(package))


def execute_stage(app,spec_path,stage,allowed_root):
    from .native_io import save_native_document
    source=Path(spec_path).resolve();out=source.parent;root=Path(allowed_root).resolve()
    if source.name!='manufacturing-spec.json' or not out.is_relative_to(root):raise ValueError('Invalid manufacturing task location')
    spec=json.loads(source.read_text(encoding='utf8'));request=ManufacturingRequest.model_validate(spec['request'])
    part=Path(spec['source']['path']).resolve()
    if not part.is_relative_to(out/'inputs'/'cad') or part.suffix.lower()!='.sldprt' or digest(part)!=spec['source']['sha256']:
        raise ValueError('Only immutable task-pinned parts are allowed')
    if type(stage) is not int or not 0<=stage<len(STAGES):raise ValueError('Invalid manufacturing stage')
    marker=out/'manufacturing-progress.json';spec_hash=digest(source);stamp=hashlib.sha256(str(out).casefold().encode()).hexdigest()[:16]
    if stage==0:
        if marker.exists():raise ValueError('Drawing task already started; create a new revision')
        record={'completed':0,'spec_sha256':spec_hash}
    else:
        record=json.loads(marker.read_text(encoding='utf8'))
        if record['completed']!=stage or record['spec_sha256']!=spec_hash:raise ValueError('Checkpoint mismatch; no native write replayed')
        if digest(record['model_path'])!=record['model_sha256']:raise ValueError('Referenced part changed before drawing execution')
    with (out/f'manufacturing-attempt-{stage}.json').open('x',encoding='utf8') as stream:
        json.dump({'stage':stage,'spec_sha256':spec_hash},stream)
    if stage==0:_prepare(app,out,spec,request,record,stamp)
    elif stage==1:_annotate(app,out,request,record)
    elif stage==2:_section(app,out,request,record)
    elif stage==3:_deliver(app,out,request,record,stamp)
    if digest(part)!=spec['source']['sha256']:raise RuntimeError('Source part bytes changed')
    record['completed']=stage+1;write_json(marker,record)
    return {'status':'ok','stage':stage,'completed_stages':stage+1,'complete':stage==len(STAGES)-1,**record}
