"""Native bounded execution of a validated design, one saved stage per call."""
from __future__ import annotations
import csv,hashlib,json,math,time,zipfile
from pathlib import Path
from .spec import DesignSpec


def _get(obj,name,*args):
    from scripts.sw_connect import get_com_member
    # A rejected RPC was not accepted by SolidWorks; other failures are never
    # blindly retried because a write could already have run.
    for attempt in range(3):
        try:return get_com_member(obj,name,*args)
        except Exception as exc:
            if getattr(exc,'hresult',None) not in {-2147418111,-2147417846} or attempt==2:raise
            time.sleep(.2*(attempt+1))


def _atomic(path,data):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)


def _exact_bounds(bodies,transform=None):
    from solidworks_mcp.automation.com_utils import typed
    data=transform or [1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.]
    result={'min':[float('inf')]*3,'max':[float('-inf')]*3}
    for body in bodies:
        native=typed(body,'IBody2')
        for label,sign in [('min',-1.),('max',1.)]:
            for axis in range(3):
                direction=[sign*data[c*3+axis] for c in range(3)]
                point=native.GetExtremePoint(*direction)
                if not point or len(point)!=4 or not point[0]:raise RuntimeError('Native exact extreme point unavailable')
                value=(sum(data[c*3+axis]*point[c+1] for c in range(3))+data[9+axis])*1000
                result[label][axis]=(min if label=='min' else max)(result[label][axis],value)
    result['size_mm']=[b-a for a,b in zip(result['min'],result['max'])]
    result['method']='IBody2.GetExtremePoint'
    return result


def _pose_data(instance):
    x,y,z=[math.radians(v) for v in instance.rotation_deg]
    cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    R=[[cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx],
       [sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx],[-sy,cy*sx,cy*cx]]
    # SW stores the transformed X,Y,Z basis vectors consecutively.
    return [R[r][c] for c in range(3) for r in range(3)]+[v/1000 for v in instance.position_mm]+[1.,0.,0.,0.]


def _fixed(doc,component,value):
    from scripts.sw_connect import create_empty_dispatch_variant
    doc.ClearSelection2(True)
    if not component.Select4(False,create_empty_dispatch_variant(),False):raise RuntimeError('Cannot select this assembly instance')
    _get(doc,'FixComponent' if value else 'UnfixComponent');doc.ClearSelection2(True)
    if bool(_get(component,'IsFixed'))!=value:raise RuntimeError('Component fixed-state readback failed')


def _cylinder_entity(component,radius_mm,axis_point_mm):
    from scripts.sw_assembly import get_component_model,get_assembly_entity
    part=get_component_model(component,resolve=True);candidates=[]
    for body in _get(part,'GetBodies2',0,False) or []:
        for face in _get(body,'GetFaces') or []:
            surface=_get(face,'GetSurface')
            if surface is None or not _get(surface,'IsCylinder'):continue
            values=list(_get(surface,'CylinderParams'))
            if abs(values[6]*1000-radius_mm)>1e-4:continue
            if axis_point_mm is not None:
                delta=[p/1000-q for p,q in zip(axis_point_mm,values[:3])];axis=values[3:6]
                along=sum(x*y for x,y in zip(delta,axis));distance=math.sqrt(sum((x-along*y)**2 for x,y in zip(delta,axis)))
                if distance>1e-6:continue
            candidates.append(face)
    if len(candidates)!=1:raise ValueError('Concentric face is missing or ambiguous; specify a unique local axis point and radius before retrying in a new task')
    return get_assembly_entity(component,candidates[0])


def _profile(doc,points,automation,plane='Front Plane'):
    from scripts.sw_part import sketch,sketch_line
    from scripts.sw_connect import create_empty_dispatch_variant
    from scripts.sw_sketch_quality import fully_define_sketch
    with sketch(doc,plane) as ref:
        manager=doc.SketchManager;old=_get(manager,'AddToDB');lines=[]
        try:
            manager.AddToDB=True
            for p,q in zip(points,points[1:]+points[:1]):
                line=sketch_line(doc,p[0]/1000,p[1]/1000,q[0]/1000,q[1]/1000)
                if line is None:raise RuntimeError('Native profile line failed')
                lines.append(line)
        finally:manager.AddToDB=old
        def relation(entities,kind):
            doc.ClearSelection2(True)
            for e in entities:
                if not e.Select4(True,create_empty_dispatch_variant()):raise RuntimeError('Native sketch selection failed')
            _get(doc,'SketchAddConstraints',kind)
        for i,line in enumerate(lines):
            relation([_get(line,'GetEndPoint2'),_get(lines[(i+1)%len(lines)],'GetStartPoint2')],'sgCOINCIDENT')
            p,q=points[i],points[(i+1)%len(points)]
            if abs(p[0]-q[0])<1e-9:relation([line],'sgVERTICAL')
            elif abs(p[1]-q[1])<1e-9:relation([line],'sgHORIZONTAL')
        with automation.dimension_input_guard():fully_define_sketch(doc)
    return ref


def _make_part(app,part,path,cad_inputs):
    from scripts.sw_connect import open_document
    from .native_io import save_native_document,save_native_copy
    def save_document(doc,path=None):return save_native_document(app,doc,path)
    from scripts.sw_part import sketch,sketch_circle,extrude_boss,extrude_cut
    from scripts.sw_sketch_quality import fully_define_sketch,inspect_model_sketches
    from integrations.czuryk.native_only import native_automation
    from integrations.czuryk.dimensioned import create_dimensioned_part,geometry_evidence
    from integrations.czuryk.step_export import export_full_step
    a=native_automation(app);imported=part.shape=='existing'
    if path.exists():raise ValueError('Existing part is preserved; create a new revision')
    if imported:
        source=cad_inputs.get(part.source_id)
        if not source:raise ValueError('Part was not supplied through the local CAD input picker')
        raw_path=Path(source['path']).resolve()
        if hashlib.sha256(raw_path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('CAD input changed after planning')
        already_open=app.GetOpenDocumentByName(str(raw_path)) is not None
        doc=open_document(app,str(raw_path),silent=True,raise_on_error=True)
        if int(_get(doc,'GetType'))!=1:raise ValueError('Existing assembly inputs require their dependency package; select individual SLDPRT parts')
        save_native_copy(app,doc,path)
        if hashlib.sha256(raw_path.read_bytes()).hexdigest()!=source['sha256']:raise RuntimeError('Native copy changed its source bytes')
        if not already_open:app.CloseDoc(str(_get(doc,'GetTitle')))
        doc=open_document(app,str(path),silent=True,raise_on_error=True)
    elif part.shape=='shaft':
        made=a.create_new_part()
        if not made.get('success'):raise RuntimeError('Cannot create native part')
        doc=app.ActiveDoc
        with sketch(doc,'Front Plane') as ref:
            if sketch_circle(doc,0,0,part.diameter_mm/2000) is None:raise RuntimeError('Circle creation failed')
            with a.dimension_input_guard():fully_define_sketch(doc)
        feature=extrude_boss(doc,ref,part.length_mm/1000,direction=False)
        if feature is None:raise RuntimeError('Shaft extrusion failed')
        feature.Name='ShaftExtrude'
    else:
        doc,_=create_dimensioned_part(a,part.geometry(),path,save_function=save_document)
        if part.shape=='enclosure':
            # Create the interior on a true offset Front plane, never screen faces.
            from scripts.sw_part import _select_first_candidate,_get_plane_name_candidates
            from integrations.czuryk.loft_native import _last_feature
            doc.ClearSelection2(True)
            if not _select_first_candidate(doc.Extension,_get_plane_name_candidates('Front Plane'),'PLANE'):raise RuntimeError('Front plane unavailable')
            doc.FeatureManager.InsertRefPlane(8,part.height_mm/1000,0,0.,0,0.)
            plane=_last_feature(doc,'RefPlane');plane.Name='CavityPlane'
            L=part.length_mm/2-part.wall_mm;W=part.width_mm/2-part.wall_mm
            ref=_profile(doc,[[-L,-W],[L,-W],[L,W],[-L,W]],a,plane='CavityPlane')
            feature=extrude_cut(doc,ref,(part.height_mm-part.wall_mm)/1000,direction=False)
            if feature is None:raise RuntimeError('Enclosure cavity cut failed')
            feature.Name='InteriorCavity';doc.ClearSelection2(True);plane.Select2(False,0);_get(doc,'BlankRefGeom')
    from .dimensions import apply as apply_dimensions
    dimension_edits=apply_dimensions(doc,part.dimension_changes) if part.dimension_changes else None
    if not _get(doc,'ForceRebuild3',False):raise RuntimeError('Native part rebuild failed')
    bodies=a._get_solid_bodies(doc)
    if not bodies:raise RuntimeError('Part contains no solid body')
    if not imported:
        for body in bodies:
            color=a._write_material_props(doc,body,[*part.color_rgb,1.,1.,.15,.15,0.,0.])
            if not color['verified']:raise RuntimeError('Part color readback failed')
    quality=inspect_model_sketches(doc)
    if not imported and quality['status']!='pass':raise RuntimeError('Generated engineering sketches are not fully defined')
    volume=sum(a._body_mass_props(b,'mm')['volume_exact'] for b in bodies)
    expected=part.expected_volume()
    if expected is not None and (len(bodies)!=1 or not math.isclose(volume,expected,rel_tol=1e-6,abs_tol=1e-3)):
        raise RuntimeError(f'Part B-Rep volume mismatch: {volume} vs {expected}')
    bounds=_exact_bounds(bodies)
    # Volume alone cannot distinguish the wrong side of the sketch plane.
    # Verify the recipe's actual material extent as well as its dimensions.
    if part.shape in {'plate','l_bracket','shaft','enclosure'}:
        if part.shape=='shaft':
            radius=part.diameter_mm/2
            expected_min=[-radius,-radius,0.];expected_max=[radius,radius,part.length_mm]
        else:
            height=part.height_mm if part.shape=='l_bracket' else part.width_mm
            depth=part.width_mm if part.shape=='l_bracket' else (part.height_mm if part.shape=='enclosure' else part.thickness_mm)
            expected_min=[-part.length_mm/2,-height/2,0.]
            expected_max=[part.length_mm/2,height/2,depth]
        if any(abs(actual-wanted)>1e-4 for label,wanted_values in [('min',expected_min),('max',expected_max)] for actual,wanted in zip(bounds[label],wanted_values)):
            raise RuntimeError('Native part extent differs from the declared recipe coordinates')
    geometry=geometry_evidence(a,doc,part.geometry()) if part.shape in {'plate','l_bracket','profile'} else None
    if geometry and not geometry['passed']:raise RuntimeError('Native outline or hole position verification failed')
    doc.ClearSelection2(True)
    if not save_document(doc,str(path)):raise RuntimeError('Native part save failed')
    step=path.with_suffix('.step');export=export_full_step(app,doc,step)
    return doc,{'id':part.id,'shape':part.shape,'path':str(path),'step':str(step),'body_count':len(bodies),
        'volume_mm3':volume,'expected_volume_mm3':expected,'sketch_quality':quality,'step_export':export,
        'parameters':part.model_dump(),'imported':imported,'exact_bounds':bounds,'geometry':geometry,'dimension_edits':dimension_edits}


def _assembly_snapshot(doc,spec,record):
    from scripts.sw_assembly import collect_mate_feature_summary
    from scripts.sw_measure import inspect_interference
    from scripts.sw_measure import collect_mass_properties
    components=list(_get(doc,'GetComponents',True) or []);actual={str(_get(c,'Name2')):c for c in components}
    rows=[];passed=len(components)==len(spec.instances)
    assembly_bounds=[]
    for instance in spec.instances:
        name=record['instances'][instance.id];component=actual.get(name)
        if component is None:raise RuntimeError('Assembly lost a component: '+instance.id)
        transform=list(_get(_get(component,'Transform2'),'ArrayData'))
        expected=_pose_data(instance)
        pose_ok=all(abs(transform[i]-expected[i])<(2e-5 if i>=9 else 1e-4) for i in range(12))
        fixed=bool(_get(component,'IsFixed'))
        if fixed!=instance.fixed:raise RuntimeError('Unexpected fixed state: '+instance.id)
        constrained=int(_get(component,'GetConstrainedStatus'))
        source_path=Path(_get(component,'GetPathName')).resolve()
        source_ok=source_path==Path(record['parts'][instance.part_id]['path']).resolve()
        constraint_ok=constrained==3 or (spec.allow_motion and not fixed and constrained==2)
        passed=passed and pose_ok and source_ok and constraint_ok
        part_model=_get(component,'GetModelDoc2');bodies=list(_get(part_model,'GetBodies2',0,False) or [])
        dimension_readback=None
        edited=record['parts'][instance.part_id].get('dimension_edits')
        if edited:
            from .dimensions import verify as verify_dimensions
            dimension_readback=verify_dimensions(part_model,edited)
            passed=passed and dimension_readback['passed']
        bounds=_exact_bounds(bodies,transform);assembly_bounds.append(bounds)
        rows.append({'id':instance.id,'name':name,'path':str(_get(component,'GetPathName')),
            'position_mm':[v*1000 for v in transform[9:12]],'rotation_matrix':transform[:9],
            'expected_position_mm':instance.position_mm,'pose_verified':pose_ok,'fixed':fixed,
            'constrained_status':constrained,'constraint_verified':constraint_ok,'source_verified':source_ok,
            'exact_bounds':bounds,
            'dimension_edits':dimension_readback,
            'suppression_state':int(_get(component,'GetSuppression'))})
    mates=collect_mate_feature_summary(doc)
    actual_mates=[m for m in mates if m['type']!='MateGroup']
    passed=passed and len(actual_mates)==len(spec.mates) and {m.id for m in spec.mates}<={m['name'] for m in actual_mates}
    interference=inspect_interference(doc,treat_coincidence_as_interference=False)
    if interference.get('errors'):raise RuntimeError('Native interference inspection unavailable: '+str(interference['errors']))
    count=interference.get('count',interference.get('interference_count'))
    if count is None:raise RuntimeError('Native interference count missing')
    passed=passed and (count==0 or spec.allow_interference)
    minimum=[min(b['min'][i] for b in assembly_bounds) for i in range(3)]
    maximum=[max(b['max'][i] for b in assembly_bounds) for i in range(3)]
    mass=collect_mass_properties(doc)
    if mass.get('errors'):raise RuntimeError('Assembly mass-property readback failed')
    from .validation import mate_readback
    mate_details=mate_readback(doc,spec,record);passed=passed and mate_details['passed']
    return {'passed':bool(passed),'component_count':len(components),'components':rows,
        'mate_features':mates,'planned_mates':len(spec.mates),'created_mates':len(record['mates']),
        'interference':interference,'allow_motion':spec.allow_motion,
        'exact_bounds':{'min':minimum,'max':maximum,'size_mm':[b-a for a,b in zip(minimum,maximum)],'method':'transformed native GetExtremePoint'},
        'mass_properties':mass,'mate_readback':mate_details,
        'review_note':'Pose/mate/interference checks do not certify load capacity, tolerance or mechanism motion'}


def execute_stage(app,spec_path,output_dir,stage,allowed_root):
    from scripts.sw_connect import open_document,new_document
    from .native_io import save_native_document
    def save_document(doc,path=None):return save_native_document(app,doc,path)
    from integrations.czuryk.native_only import native_automation
    source=Path(spec_path).resolve();out=Path(output_dir).resolve();root=Path(allowed_root).resolve()
    if source.parent!=out or source.name!='design-spec.json' or not out.is_relative_to(root):raise ValueError('Design and outputs must stay in this task directory')
    if source.stat().st_size>100000:raise ValueError('Design exceeds the bounded schema size')
    spec=DesignSpec.model_validate_json(source.read_text(encoding='utf-8'));stages=spec.stages()
    if not 0<=stage<len(stages):raise ValueError('Invalid engineering stage')
    digest=hashlib.sha256(source.read_bytes()).hexdigest();marker=out/'engineering-progress.json';stamp=hashlib.sha256(str(out).casefold().encode()).hexdigest()[:16]
    if stage==0:
        if marker.exists():raise ValueError('This design was already started; preserve it and create a revision')
        record={'spec_sha256':digest,'completed':0,'parts':{},'instances':{},'mates':[],'history':[]}
    else:
        record=json.loads(marker.read_text(encoding='utf-8'))
        if record['completed']!=stage or record['spec_sha256']!=digest:raise ValueError('Checkpoint or design changed; no stage was replayed')
    cad_file=out/'cad-inputs.json';cad_inputs=json.loads(cad_file.read_text(encoding='utf-8')) if cad_file.exists() else {}
    # Imported paths can only identify immutable, pinned local inputs.
    for entry in cad_inputs.values():
        if not Path(entry['path']).resolve().is_relative_to(out/'inputs'/'cad'):raise ValueError('CAD input is outside this task')
    current=stages[stage];kind=current['kind'];a=native_automation(app)
    if kind=='part':
        part=next(p for p in spec.parts if p.id==current['id']);folder=out/'parts';folder.mkdir(exist_ok=True)
        doc,made=_make_part(app,part,folder/(part.id+'_'+stamp+'.SLDPRT'),cad_inputs)
        record['parts'][part.id]=made
        record['active_path']=str(_get(doc,'GetPathName'))
        if spec.document=='assembly':app.CloseDoc(str(_get(doc,'GetTitle')))
    elif kind=='assembly':
        from scripts.sw_assembly import add_component,_activate_model_document
        from solidworks_mcp.automation.com_utils import typed
        import pythoncom,win32com.client
        doc=new_document(app,'assembly');path=out/('assembly_'+stamp+'.SLDASM')
        if not save_document(doc,str(path)):raise RuntimeError('Assembly save failed')
        for instance in spec.instances:
            part_path=record['parts'][instance.part_id]['path']
            component=add_component(doc,part_path,*[v/1000 for v in instance.position_mm],sw=app)
            if component is None:raise RuntimeError('Native component insertion failed')
            component.Name2=instance.id;_fixed(doc,component,False)
            utility=typed(_get(app,'GetMathUtility'),'IMathUtility')
            data=win32com.client.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,_pose_data(instance))
            component.Transform2=utility.CreateTransform(data)
            if instance.fixed:_fixed(doc,component,True)
            record['instances'][instance.id]=str(_get(component,'Name2'))
        _get(doc,'ForceRebuild3',False);doc.ClearSelection2(True)
        if not save_document(doc,str(path)):raise RuntimeError('Assembly with components was not saved')
        record['assembly_path']=str(path);record['active_path']=str(path)
    else:
        doc=app.ActiveDoc
        if doc is None or Path(_get(doc,'GetPathName')).resolve()!=Path(record['active_path']).resolve():raise RuntimeError('Active document changed; no write was sent')
        if kind=='mate':
            from scripts.sw_assembly import (get_component_feature_entity,select_entities_for_mate,
                add_mate5_checked)
            mate_spec=next(m for m in spec.mates if m.id==current['id']);components={str(_get(c,'Name2')):c for c in (_get(doc,'GetComponents',True) or [])}
            ca=components[record['instances'][mate_spec.a]];cb=components[record['instances'][mate_spec.b]]
            if mate_spec.kind=='concentric':
                fa=_cylinder_entity(ca,mate_spec.radius_a_mm,mate_spec.axis_point_a_mm)
                fb=_cylinder_entity(cb,mate_spec.radius_b_mm,mate_spec.axis_point_b_mm)
                select_entities_for_mate(doc,fa,fb,mark=1)
                # Closest preserves the declared pose for inner/outer cylinders;
                # forced alignment can flip a shaft before rotation is locked.
                mate=add_mate5_checked(doc,1,align=2,lock_rotation=mate_spec.lock_rotation,name=mate_spec.id)
            else:
                planes={'XY':'Front Plane','XZ':'Top Plane','YZ':'Right Plane'}
                ea=get_component_feature_entity(ca,planes[mate_spec.plane_a]);eb=get_component_feature_entity(cb,planes[mate_spec.plane_b])
                select_entities_for_mate(doc,ea,eb,mark=1)
                mate=add_mate5_checked(doc,0 if mate_spec.kind=='coincident' else 5,
                    align={'aligned':0,'anti_aligned':1,'closest':2}[mate_spec.alignment],flip=mate_spec.flip,distance=mate_spec.distance_mm/1000,name=mate_spec.id)
            if mate is None:raise RuntimeError('Native mate was not created')
            try:feature=_get(mate,'GetFeature');feature.Name=mate_spec.id
            except Exception:pass
            if not _get(doc,'ForceRebuild3',False):raise RuntimeError('Assembly mate rebuild failed')
            record['mates'].append(mate_spec.model_dump())
            if not save_document(doc):raise RuntimeError('Mate checkpoint save failed')
        elif kind=='check':
            path=str(_get(doc,'GetPathName'));title=str(_get(doc,'GetTitle'))
            if not save_document(doc):raise RuntimeError('Final native save failed')
            app.CloseDoc(title);doc=open_document(app,path,silent=True,raise_on_error=True)
            if not _get(doc,'ForceRebuild3',False):raise RuntimeError('Saved design did not rebuild')
            if spec.document=='assembly':record['verification']=_assembly_snapshot(doc,spec,record)
            else:
                from scripts.sw_sketch_quality import inspect_model_sketches
                part=spec.parts[0];bodies=a._get_solid_bodies(doc);quality=inspect_model_sketches(doc)
                volume=sum(a._body_mass_props(b,'mm')['volume_exact'] for b in bodies);expected=part.expected_volume()
                record['verification']={'passed':bool(bodies) and volume>0 and (expected is None or math.isclose(volume,expected,rel_tol=1e-6,abs_tol=1e-3)) and (part.shape=='existing' or quality['status']=='pass'),
                    'body_count':len(bodies),'volume_mm3':volume,'sketch_quality':quality,'exact_bounds':_exact_bounds(bodies)}
                edited=record['parts'][part.id].get('dimension_edits')
                if edited:
                    from .dimensions import verify as verify_dimensions
                    readback=verify_dimensions(doc,edited)
                    record['verification']['dimension_edits']=readback
                    record['verification']['passed']=record['verification']['passed'] and readback['passed']
                    if not readback['passed']:raise RuntimeError('Saved/reopened local dimension edits did not verify')
            record['verification']['save_reopen_verified']=True
        elif kind=='delivery':
            from integrations.czuryk.step_export import export_full_step
            from scripts.sw_export import export_to_step
            from .previews import export_design_previews
            path=Path(record['active_path']);step=out/(path.stem+'.step')
            source_receipts=[]
            for asset,entry in cad_inputs.items():
                actual=hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest()
                source_receipts.append({'id':asset,'before_sha256':entry['sha256'],'after_sha256':actual,'unchanged':actual==entry['sha256']})
            if not all(r['unchanged'] for r in source_receipts):raise RuntimeError('An input part changed during this task')
            record['verification']['source_inputs']=source_receipts
            previous_file=out/'revision-source.json'
            if previous_file.exists():
                previous=[]
                for entry in json.loads(previous_file.read_text(encoding='utf-8'))['files']:
                    previous_path=Path(entry['path']).resolve()
                    if not previous_path.is_relative_to(root) or (previous_path.suffix.lower() not in {'.sldasm','.sldprt'} and previous_path.name!='design-spec.json'):raise ValueError('Previous revision receipt path is invalid')
                    actual=hashlib.sha256(previous_path.read_bytes()).hexdigest()
                    previous.append({**entry,'after_sha256':actual,'unchanged':actual==entry['sha256']})
                if not all(r['unchanged'] for r in previous):raise RuntimeError('Previous revision files changed during this task')
                record['verification']['previous_files_preserved']={'passed':True,'files':previous}
            if spec.document=='part':export_full_step(app,doc,step)
            else:
                old=int(_get(app,'GetUserPreferenceIntegerValue',75));old_geometry=int(_get(app,'GetUserPreferenceIntegerValue',142))
                try:
                    if not _get(app,'SetUserPreferenceIntegerValue',75,214) or not _get(app,'SetUserPreferenceIntegerValue',142,0):raise RuntimeError('Cannot select solid STEP AP214')
                    doc.ClearSelection2(True)
                    if not export_to_step(doc,str(step)):raise RuntimeError('Assembly STEP export failed')
                finally:
                    _get(app,'SetUserPreferenceIntegerValue',75,old);_get(app,'SetUserPreferenceIntegerValue',142,old_geometry)
                from .validation import verify_assembly_step
                expected_bodies=sum(record['parts'][i.part_id]['body_count'] for i in spec.instances)
                record['verification']['step_reimport']=verify_assembly_step(app,doc,step,record['verification'],expected_bodies)
                doc=open_document(app,str(path),silent=True,raise_on_error=True)
                with (out/'assembly_bom.csv').open('w',newline='',encoding='utf-8-sig') as stream:
                    writer=csv.writer(stream);writer.writerow(['part_id','label','quantity','native_file'])
                    for p in spec.parts:writer.writerow([p.id,p.label,sum(i.part_id==p.id for i in spec.instances),Path(record['parts'][p.id]['path']).name])
                with (out/'assembly_bom.csv').open(encoding='utf-8-sig',newline='') as stream:record['bom_rows']=list(csv.DictReader(stream))
            manifest=export_design_previews(a,doc,out)
            previews=[str(out/v['file']) for v in manifest['views']]
            record['preview_manifest']=manifest
            save_document(doc)
            record['step_path']=str(step);record['preview_paths']=previews
            package=out/('CAD_delivery_'+stamp+'.zip')
            paths={Path(p['path']) for p in record['parts'].values()}|{Path(record['active_path']),step,out/'design-spec.json'}
            if spec.document=='assembly':paths.add(out/'assembly_bom.csv')
            paths.update(Path(p) for p in previews)
            paths.add(out/'preview-manifest.json')
            record['package']=str(package)
    record['completed']=stage+1;record['history'].append(current);_atomic(marker,record)
    complete=stage+1==len(stages)
    if complete:
        from .package import build_delivery
        proof={'native_control_only':True,'verification':record['verification'],'parts':record['parts'],
            'spec_sha256':record['spec_sha256'],'bom_rows':record.get('bom_rows',[]),'preview_manifest':record.get('preview_manifest')}
        record.update(build_delivery(out,package,paths,proof))
        _atomic(marker,record)
        _atomic(out/'design-acceptance.json',{'status':'passed' if record['verification']['passed'] else 'review_required',
            'native_control_only':True,'computer_use':False,**record})
    result={'status':'ok','success':True,'complete':complete,'stage':stage,'completed_stages':stage+1,
        'total_stages':len(stages),'stage_label':current['label'],'document':{'path':record['active_path'],
        'title':str(_get(app.ActiveDoc,'GetTitle')) if app.ActiveDoc is not None else '',
        'type':2 if spec.document=='assembly' and kind!='part' else 1},
        'part_count':len(record['parts']),'component_count':len(record['instances']),'mate_count':len(record['mates'])}
    if complete:result.update(verification=record['verification'],parts=record['parts'],step_path=record['step_path'],package=record['package'],preview_paths=record['preview_paths'],
        preview_manifest=record.get('preview_manifest'),
        package_verified=record['package_verified'],package_entries=record['package_entries'],
        package_hashes=record['package_hashes'],package_sha256=record['package_sha256'],bom_rows=record.get('bom_rows',[]))
    return result
