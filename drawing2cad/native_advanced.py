"""Native sketches, merged height layers and audited depth-controlled cuts."""
from __future__ import annotations
import json,math,hashlib,zipfile,sys
from pathlib import Path


def _get(obj,name,*args):
    from scripts.sw_connect import get_com_member
    return get_com_member(obj,name,*args)


def _plane(doc,z,name):
    if abs(z)<1e-8:return 'Front Plane'
    from scripts.sw_part import _select_first_candidate,_get_plane_name_candidates
    from integrations.czuryk.loft_native import _last_feature
    doc.ClearSelection2(True)
    if not _select_first_candidate(doc.Extension,_get_plane_name_candidates('Front Plane'),'PLANE'):raise RuntimeError('Front plane unavailable')
    created=doc.FeatureManager.InsertRefPlane(8,z/1000,0,0.,0,0.)
    if created is None:raise RuntimeError('Native offset plane creation failed')
    plane=_last_feature(doc,'RefPlane');plane.Name=name
    return name


def _segments(points):
    return [{'kind':'line','start':p,'end':q} for p,q in zip(points,points[1:]+points[:1])]


def _sketch(doc,loops,automation,plane,coordinate_map=None):
    from scripts.sw_connect import create_empty_dispatch_variant
    from scripts.sw_part import sketch,sketch_line,sketch_circle
    from scripts.sw_sketch_quality import fully_define_sketch
    with sketch(doc,plane) as ref:
        if coordinate_map is not None:loops=coordinate_map(loops)
        manager=doc.SketchManager;old=_get(manager,'AddToDB');made=[]
        try:
            manager.AddToDB=True
            for loop in loops:
                entities=[]
                for s in loop:
                    if s['kind']=='line':entity=sketch_line(doc,*[v/1000 for v in s['start']],*[v/1000 for v in s['end']])
                    elif s['kind']=='circle':entity=sketch_circle(doc,*[v/1000 for v in s['center']],s['radius']/1000)
                    else:entity=manager.CreateArc(s['center'][0]/1000,s['center'][1]/1000,0.,s['start'][0]/1000,s['start'][1]/1000,0.,s['end'][0]/1000,s['end'][1]/1000,0.,1 if s['ccw'] else -1)
                    if entity is None:raise RuntimeError('Native advanced sketch entity failed')
                    entities.append((entity,s))
                made.append(entities)
        finally:manager.AddToDB=old
        def relation(objects,kind):
            doc.ClearSelection2(True)
            for obj in objects:
                if not obj.Select4(True,create_empty_dispatch_variant()):raise RuntimeError('Native sketch entity selection failed')
            _get(doc,'SketchAddConstraints',kind)
        for loop in made:
            if len(loop)==1 and loop[0][1]['kind']=='circle':continue
            for i,(entity,s) in enumerate(loop):
                relation([_get(entity,'GetEndPoint2'),_get(loop[(i+1)%len(loop)][0],'GetStartPoint2')],'sgCOINCIDENT')
                if s['kind']=='line':
                    if abs(s['start'][0]-s['end'][0])<1e-8:relation([entity],'sgVERTICAL')
                    elif abs(s['start'][1]-s['end'][1])<1e-8:relation([entity],'sgHORIZONTAL')
        with automation.dimension_input_guard():fully_define_sketch(doc)
    return ref


def _depth(feature,expected,through):
    definition=_get(feature,'GetDefinition')
    if definition is None:raise RuntimeError('Native extrusion definition unavailable')
    end=int(_get(definition,'GetEndCondition',True));actual=float(_get(definition,'GetDepth',True))*1000
    if end!=(1 if through else 0) or (not through and abs(actual-expected)>1e-4):raise RuntimeError('Native cut depth/end-condition readback failed')
    return {'feature':str(_get(feature,'Name')),'end_condition':end,'depth_mm':None if through else actual,'through_all':through,'definition_readback':True}


def create_part(app,automation,spec):
    if spec['kind']=='orthographic_analytic':
        from .native_analytic import create_part as create
        return create(app,automation,spec)
    from scripts.sw_part import extrude_boss,extrude_cut
    from .native import _shift
    made=automation.create_new_part()
    if not made.get('success'):raise RuntimeError('Cannot create native advanced part')
    doc=app.ActiveDoc;features=[]
    if spec['kind']=='orthographic':
        for i,layer in enumerate(spec['layers']):
            print('Native multiview layer',i+1,flush=True,file=sys.stderr)
            plane=_plane(doc,layer['z0'],'LayerPlane'+str(i+1))
            ref=_sketch(doc,[_segments(points) for points in layer['profiles']],automation,plane)
            feature=extrude_boss(doc,ref,(layer['z1']-layer['z0'])/1000,direction=False,merge=True)
            if feature is None:raise RuntimeError('Native multiview height layer failed')
            feature.Name='MultiViewLayer'+str(i+1);features.append({'feature':str(feature.Name),'z0_mm':layer['z0'],'z1_mm':layer['z1']})
    else:
        b=spec['bounds_mm'];origin=[(b[0]+b[2])/2,(b[1]+b[3])/2]
        ref=_sketch(doc,[[_shift(s,origin) for s in spec['outer']]],automation,'Front Plane')
        feature=extrude_boss(doc,ref,spec['size_mm'][2]/1000,direction=False)
        if feature is None:raise RuntimeError('Native advanced base extrusion failed')
        feature.Name='DrawingBase'
    if len(automation._get_solid_bodies(doc))!=1:raise RuntimeError('Multiview layers did not merge into one solid')
    for hole in spec['holes']:
        print('Native hole',hole['id'],hole['kind'],flush=True,file=sys.stderr)
        plane=_plane(doc,hole['entry_z_mm'],hole['id']+'_Entry')
        operations=[('Base',hole['radius_mm'],hole['cut_depth_mm'],hole['through'])]
        if hole['counterbore_radius_mm'] is not None:operations.append(('Recess',hole['counterbore_radius_mm'],hole['counterbore_depth_mm'],False))
        hole['native_features']=[]
        for label,radius,depth,through in operations:
            ref=_sketch(doc,[[{'kind':'circle','center':[hole['x_mm'],hole['y_mm']],'radius':radius}]],automation,plane)
            feature=extrude_cut(doc,ref,0 if through else depth/1000,direction=False)
            if feature is None:raise RuntimeError('Native hole cut failed: '+hole['id']+' '+label)
            feature.Name=hole['id']+'_'+label
            hole['native_features'].append(_depth(feature,depth,through))
    if not _get(doc,'ForceRebuild3',False):raise RuntimeError('Advanced part rebuild failed')
    return doc,features


def native_projections(planar_faces,spec):
    """Project exact native straight B-Rep edges of planar faces, filling bores."""
    from shapely.geometry import LineString,Polygon
    from shapely.ops import unary_union,polygonize
    axes={'top':(0,1),'front':(0,2),'right':(1,2)};records={};L,W,_=spec['size_mm']
    for role,(u,v) in axes.items():
        regions=[];projected_edges=[]
        for edges in planar_faces:
            lines=[]
            for p,q in edges:
                a,b=[p[u],p[v]],[q[u],q[v]]
                if math.dist(a,b)>1e-5:lines.append(LineString([a,b]));projected_edges.append(LineString([a,b]))
            regions.extend(polygonize(unary_union(lines)))
        actual=unary_union(regions)
        origin=(L/2,W/2) if role=='top' else (L/2,0) if role=='front' else (W/2,0)
        expected=Polygon([[a-origin[0],b-origin[1]] for a,b in spec['projections'][role]])
        error=actual.symmetric_difference(expected).area
        network=unary_union(projected_edges).buffer(1e-4)
        missing=sum(LineString([[x-origin[0],y-origin[1]] for x,y in line]).difference(network).length for line in spec.get('detail_lines',{}).get(role,[]))
        records[role]={'passed':error<1e-4 and missing<.001,'difference_area_mm2':error,'unmatched_detail_length_mm':missing,'method':'native planar B-Rep straight edges; holes filled for exterior-silhouette check'}
    return {'passed':all(r['passed'] for r in records.values()),'views':records}


def measure(automation,doc,spec):
    if spec['kind']=='orthographic_analytic':
        from .native_analytic import measure as read
        return read(automation,doc,spec)
    from engineering.native import _exact_bounds
    bodies=automation._get_solid_bodies(doc);volume=sum(automation._body_mass_props(b,'mm')['volume_exact'] for b in bodies);bounds=_exact_bounds(bodies)
    size=all(abs(a-b)<1e-4 for a,b in zip(bounds['size_mm'],spec['size_mm']))
    cylinders=[];disks=[];planar_faces=[]
    for body in bodies:
        for face in _get(body,'GetFaces') or []:
            surface=_get(face,'GetSurface');circles=[];edge_count=0;straight=[];is_plane=bool(_get(surface,'IsPlane'))
            for edge in _get(face,'GetEdges') or []:
                edge_count+=1;curve=_get(edge,'GetCurve')
                if _get(curve,'IsCircle'):
                    values=list(_get(curve,'CircleParams'));circles.append({'center_mm':[x*1000 for x in values[:3]],'radius_mm':values[6]*1000})
                elif is_plane and _get(curve,'IsLine'):
                    start,end=_get(edge,'GetStartVertex'),_get(edge,'GetEndVertex')
                    if start is not None and end is not None:straight.append(([v*1000 for v in _get(start,'GetPoint')],[v*1000 for v in _get(end,'GetPoint')]))
            if straight:planar_faces.append(straight)
            if _get(surface,'IsCylinder'):
                values=list(_get(surface,'CylinderParams'))
                if abs(abs(values[5])-1)<1e-6 and len(circles)>=2:
                    cylinders.append({'center_mm':[x*1000 for x in values[:3]],'radius_mm':values[6]*1000,'z_min':min(c['center_mm'][2] for c in circles),'z_max':max(c['center_mm'][2] for c in circles)})
            elif is_plane and len(circles)==1 and edge_count==1:disks.extend(circles)
    evidence=[]
    for hole in spec['holes']:
        split=hole['entry_z_mm']-(hole['counterbore_depth_mm'] or 0)
        expected=[(hole['radius_mm'],hole['bottom_z_mm'],split)]
        if hole['counterbore_radius_mm'] is not None:expected.append((hole['counterbore_radius_mm'],split,hole['entry_z_mm']))
        matches=[]
        for radius,low,high in expected:
            match=[c for c in cylinders if math.hypot(c['center_mm'][0]-hole['x_mm'],c['center_mm'][1]-hole['y_mm'])<1e-4 and abs(c['radius_mm']-radius)<1e-4 and abs(c['z_min']-low)<1e-4 and abs(c['z_max']-high)<1e-4]
            matches.append(bool(match))
        bottom=any(math.dist(d['center_mm'],[hole['x_mm'],hole['y_mm'],hole['bottom_z_mm']])<1e-4 and abs(d['radius_mm']-hole['radius_mm'])<1e-4 for d in disks)
        terminal_ok=not bottom if hole['through'] else bottom
        evidence.append({'id':hole['id'],'kind':hole['kind'],'expected_cylinder_intervals_mm':expected,'cylinder_intervals_verified':all(matches),'flat_bottom_disk_present':bottom,'terminal_verified':terminal_ok,'native_features':hole['native_features'],'passed':all(matches) and terminal_ok})
    projection=native_projections(planar_faces,spec) if spec['kind']=='orthographic' else {'passed':True,'method':'single profile: exact size, volume and cylinder intervals'}
    volume_ok=math.isclose(volume,spec['expected_volume_mm3'],rel_tol=1e-6,abs_tol=.001)
    return {'passed':len(bodies)==1 and size and volume_ok and projection['passed'] and all(h['passed'] for h in evidence),'body_count':len(bodies),'volume_mm3':volume,'expected_volume_mm3':spec['expected_volume_mm3'],'exact_bounds':bounds,'size_verified':size,'volume_verified':volume_ok,'holes':evidence,'native_projections':projection}


def build(app,automation,spec,task,source,sha256):
    from scripts.sw_connect import open_document
    from scripts.sw_sketch_quality import inspect_model_sketches
    from engineering.native_io import save_native_document
    from integrations.czuryk.step_export import export_full_step
    from engineering.previews import export_design_previews
    from solidworks_mcp.automation.com_utils import resolve_solidworks_constant as constant
    from .native import digest,artifact_paths
    # The caller reserved the native operation before reaching this function.
    output,step_path=artifact_paths(task);doc,features=create_part(app,automation,spec)
    print('Native advanced geometry readback',flush=True,file=sys.stderr)
    measured=measure(automation,doc,spec);quality=inspect_model_sketches(doc)
    (task/'drawing-advanced-spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf8')
    (task/'drawing-geometry-before-save.json').write_text(json.dumps(measured,ensure_ascii=False,indent=2),encoding='utf8')
    if not measured['passed'] or quality['status']!='pass':raise RuntimeError('Advanced native geometry or sketch editability failed readback')
    print('Native advanced save/reopen',flush=True,file=sys.stderr)
    save_native_document(app,doc,output);app.CloseDoc(str(_get(doc,'GetTitle')))
    doc=open_document(app,str(output),read_only=False,silent=True,raise_on_error=True)
    # Re-read feature definitions, not just the in-memory requested depths.
    actual={}
    feature=_get(doc,'FirstFeature')
    while feature is not None:actual[str(_get(feature,'Name'))]=feature;feature=_get(feature,'GetNextFeature')
    for hole in spec['holes']:
        if spec['kind']=='orthographic_analytic':
            from .native_analytic import read_feature
            hole['native_features']=[read_feature(actual[r['feature']],r) for r in hole['native_features']]
        else:hole['native_features']=[_depth(actual[r['feature']],r['depth_mm'] or 0,r['through_all']) for r in hole['native_features']]
    print('Native reopened geometry/depth readback',flush=True,file=sys.stderr)
    reopened=measure(automation,doc,spec);quality=inspect_model_sketches(doc)
    if not reopened['passed'] or quality['status']!='pass':raise RuntimeError('Saved/reopened advanced drawing model failed geometry/depth/constraint checks')
    step=export_full_step(app,doc,step_path)
    hide=constant('swViewDisplayHideAllTypes');option=constant('swDetailingNoOptionSpecified');old=doc.Extension.GetUserPreferenceToggle(hide,option)
    try:
        doc.Extension.SetUserPreferenceToggle(hide,option,True);previews=export_design_previews(automation,doc,task)
    finally:doc.Extension.SetUserPreferenceToggle(hide,option,old)
    if digest(source)!=sha256:raise RuntimeError('Original drawing changed')
    report={'status':'ok','success':True,'document':{'title':str(_get(doc,'GetTitle')),'path':str(output),'type':1},'reconstruction':spec['kind'],'geometry':measured,'saved_reopened_geometry':reopened,'sketch_quality':quality,'source_sha256':sha256,'source_unchanged':True,'selected_views':spec['views'],'dimension_policy':spec['dimension_policy'],'assumptions':spec['assumptions'],'features':features,'step':step,'previews':previews,'native_only_audit':automation.native_only_audit,'paid_model_calls':0}
    (task/'drawing-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    files=[output,step_path,task/'drawing-acceptance.json',task/'drawing-inspection.json',task/'drawing-advanced-spec.json',task/'drawing-contours.png',task/'preview-manifest.json']+[task/v['file'] for v in previews['views']]
    files=[p for p in files if p.is_file()]
    (task/'SHA256SUMS-drawing.txt').write_text(''.join(digest(p)+'  '+p.relative_to(task).as_posix()+'\n' for p in files),encoding='utf8')
    with zipfile.ZipFile(task/'Drawing_delivery.zip','x',zipfile.ZIP_DEFLATED) as archive:
        for p in [*files,task/'SHA256SUMS-drawing.txt']:archive.write(p,p.relative_to(task).as_posix())
    with zipfile.ZipFile(task/'Drawing_delivery.zip') as archive:
        if archive.testzip() is not None:raise RuntimeError('Advanced delivery ZIP integrity failed')
        for p in files:
            if hashlib.sha256(archive.read(p.relative_to(task).as_posix())).hexdigest()!=digest(p):raise RuntimeError('Advanced delivery ZIP member hash failed')
    return report
