"""Native SW2024 multi-body ellipse lofts, built in resumable bounded batches.

API patterns were cross-checked against MIT hjbaard/SolidWorks-MCP and
HarrierPigeon/Solidworks-MCP-Server, plus official SW2024 documentation.
No upstream server or arbitrary user code is executed.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

from .loft_spec import resolved_components

BATCH_SIZE = 2


def _last_feature(doc, kind):
    from scripts.sw_connect import get_com_member as get
    feature=get(doc,'FirstFeature');last=None
    while feature is not None:
        if get(feature,'GetTypeName2')==kind:last=feature
        feature=get(feature,'GetNextFeature')
    if last is None:raise RuntimeError('Native '+kind+' was not created')
    return last


def _world(axis, s, u, v):
    return {'X':(s,u,v),'Y':(u,s,v),'Z':(u,v,s)}[axis]


def _dimension_ellipse(doc, ellipse):
    """Expose both ellipse radii as editable, axis-aligned construction lines."""
    from scripts.sw_connect import get_com_member as get,create_empty_dispatch_variant
    center=get(ellipse,'GetCenterPoint2')
    for name in ('GetMajorPoint2','GetMinorPoint2'):
        tip=get(ellipse,name)
        c=[float(get(center,k)) for k in ('X','Y','Z')]
        t=[float(get(tip,k)) for k in ('X','Y','Z')]
        line=doc.SketchManager.CreateLine(*c,*t)
        line.ConstructionGeometry=True
        for a,b in ((get(line,'GetStartPoint2'),center),(get(line,'GetEndPoint2'),tip)):
            doc.ClearSelection2(True)
            for e in (a,b):
                if not e.Select4(True,create_empty_dispatch_variant()):raise RuntimeError('Cannot select ellipse axis endpoint')
            get(doc,'SketchAddConstraints','sgCOINCIDENT')
        doc.ClearSelection2(True)
        if not line.Select4(False,create_empty_dispatch_variant()):raise RuntimeError('Cannot select ellipse construction axis')
        get(doc,'SketchAddConstraints','sgHORIZONTAL' if abs(t[0]-c[0])>abs(t[1]-c[1]) else 'sgVERTICAL')
    doc.ClearSelection2(True)


def add_component(automation, doc, component):
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_part import _select_first_candidate,_get_plane_name_candidates
    from scripts.sw_sketch_quality import fully_define_sketch
    from solidworks_mcp.automation.com_utils import transform_point
    base={'X':'Right Plane','Y':'Top Plane','Z':'Front Plane'}[component.axis]
    profiles=[];support=[];qualities=[]
    before=len(automation._get_solid_bodies(doc))
    for i,section in enumerate(component.sections):
        doc.ClearSelection2(True)
        selected_base=_select_first_candidate(doc.Extension,_get_plane_name_candidates(base),'PLANE')
        if not selected_base:
            raise RuntimeError('Native reference plane unavailable: '+base)
        if abs(section.station_mm)>.00001:
            base_feature=automation._find_feature(doc,selected_base)
            base_data=get(get(get(base_feature,'GetSpecificFeature2'),'Transform'),'ArrayData')
            normal=float(base_data[6+{'X':0,'Y':1,'Z':2}[component.axis]])
            if abs(normal)<.99:raise RuntimeError('Base plane does not have the requested principal normal')
            flip=section.station_mm*normal<0
            doc.FeatureManager.InsertRefPlane(8 | (256 if flip else 0),abs(section.station_mm)/1000,0,0.,0,0.)
            plane=_last_feature(doc,'RefPlane');plane.Name=component.name+'_P'+str(i)
            if not plane.Select2(False,0):raise RuntimeError('Cannot select offset plane')
            support.append(plane)
        doc.SketchManager.InsertSketch(True)
        try:
            active=get(doc.SketchManager,'ActiveSketch')
            data=get(get(active,'ModelToSketchTransform'),'ArrayData')
            def local(u,v):
                p=transform_point(data,[q/1000 for q in _world(component.axis,section.station_mm,u,v)])
                if abs(p[2])>1e-7:raise RuntimeError('Offset plane did not match the requested world station')
                return p
            c=local(section.u_mm,section.v_mm)
            u=local(section.u_mm+section.radius_u_mm,section.v_mm)
            v=local(section.u_mm,section.v_mm+section.radius_v_mm)
            if section.radius_v_mm>section.radius_u_mm:u,v=v,u
            original_add=get(doc.SketchManager,'AddToDB')
            try:
                doc.SketchManager.AddToDB=True
                entity=doc.SketchManager.CreateEllipse(*c,*u,*v)
                if entity is None:raise RuntimeError('Native ellipse was not created')
                _dimension_ellipse(doc,entity)
            finally:doc.SketchManager.AddToDB=original_add
            with automation.dimension_input_guard():quality=fully_define_sketch(doc)
            qualities.append(quality)
        finally:
            if get(doc.SketchManager,'ActiveSketch') is not None:
                doc.SketchManager.InsertSketch(True)
        profile=_last_feature(doc,'ProfileFeature')
        profile.Name=component.name+'_S'+str(i);profiles.append(profile)
    doc.ClearSelection2(True)
    for profile in profiles:
        if not profile.Select2(True,1):raise RuntimeError('Cannot select closed loft profile')
    feature=doc.FeatureManager.InsertProtrusionBlend2(False,True,False,1.,0,0,1.,1.,True,True,
        False,0.,0.,0,False,False,True,0)
    if feature is None:raise RuntimeError('Native solid loft failed: '+component.name)
    feature.Name=component.name
    if not get(doc,'ForceRebuild3',False):raise RuntimeError('Native loft rebuild failed')
    bodies=automation._get_solid_bodies(doc)
    if len(bodies)!=before+1:raise RuntimeError('Loft must create exactly one separate solid')
    faces=get(feature,'GetFaces') or []
    if not faces:raise RuntimeError('Loft has no B-Rep faces')
    body=get(faces[0],'GetBody');body.Name=component.name+'_Solid'
    # SW2024 clamps ambient/diffuse to 1 on these body appearances; preserve
    # those supported values and verify the actual RGB/specular readback.
    material=automation._write_material_props(doc,body,[*component.color_rgb,1.,1.,.15,.15,0.,0.])
    if not material['verified']:raise RuntimeError('Native color did not read back correctly')
    for plane in support:
        doc.ClearSelection2(True)
        if plane.Select2(False,0):get(doc,'BlankRefGeom')
    doc.ClearSelection2(True)
    mass=automation._body_mass_props(body,'mm')
    if not mass or not math.isfinite(mass['volume_exact']) or mass['volume_exact']<=1e-5:
        raise RuntimeError('Loft did not produce a positive-volume native solid')
    print('NATIVE_LOFT_COMPONENT '+component.name, file=sys.stderr,flush=True)
    return {'name':component.name,'feature_type':str(get(feature,'GetTypeName2')),
        'profiles':len(profiles),'volume_mm3':mass['volume_exact'],'color_verified':True,
        'color_rgb':component.color_rgb,'all_profiles_fully_defined':all(q['status']=='pass' for q in qualities)}


def export_scene_views(automation, doc, directory):
    from scripts.sw_connect import get_com_member as get
    views=[('scene_isometric',[.5,.8,-.35]),('scene_front',[0,1,0]),('scene_side',[1,0,0]),('scene_top',[0,0,-1])]
    paths=[]
    for name,direction in views:
        result=automation.set_view_orientation(view_direction=direction,up_direction=[0,0,1] if name!='scene_top' else [0,1,0])
        if not result.get('success'):raise RuntimeError('Native scene view failed: '+name)
        path=Path(directory)/(name+'.bmp')
        if not get(doc,'SaveBMP',str(path),1600,1000):raise RuntimeError('Native preview export failed')
        paths.append(str(path))
    automation.set_view_orientation(view_direction=[.5,.8,-.35],up_direction=[0,0,1])
    return paths


def build_batch(automation, spec, source, output, component_start):
    from scripts.sw_connect import get_com_member as get,save_document
    from scripts.sw_sketch_quality import inspect_model_sketches
    components=resolved_components(spec)
    marker=output.parent/'loft-progress.json'
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if not components or component_start<0 or component_start>=len(components) or component_start%BATCH_SIZE:
        raise ValueError('Invalid native loft batch index')
    if component_start==0:
        if output.exists() or marker.exists():raise ValueError('Existing native outputs are preserved')
        made=automation.create_new_part()
        if not made.get('success'):raise RuntimeError(made.get('message','Cannot create native part'))
        doc=automation.app.ActiveDoc
        record={'spec_sha256':digest,'completed':[],'component_count':len(components)}
    else:
        record=json.loads(marker.read_text(encoding='utf-8'))
        doc=automation.app.ActiveDoc
        if (record['spec_sha256']!=digest or len(record['completed'])!=component_start
                or Path(get(doc,'GetPathName')).resolve()!=output):
            raise ValueError('Active document or saved batch does not match this task')
    end=min(component_start+BATCH_SIZE,len(components))
    for component in components[component_start:end]:
        record['completed'].append(add_component(automation,doc,component))
    if not save_document(doc,str(output)):raise RuntimeError('Native loft batch was not saved')
    temporary=marker.with_suffix('.tmp')
    temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(marker)
    complete=end==len(components)
    result={'status':'ok' if complete else 'in_progress','success':True,'complete':complete,
        'completed_components':end,'component_count':len(components),'next_component':end if not complete else None,
        'document':{'title':str(get(doc,'GetTitle')),'path':str(output),'type':1},
        'native_components':record['completed'],'native_only_audit':automation.native_only_audit}
    if complete:
        bodies=automation._get_solid_bodies(doc)
        quality=inspect_model_sketches(doc)
        if len(bodies)!=len(components) or quality['status']!='pass':
            raise RuntimeError('Final native body count or sketch-constraint verification failed')
        result.update(sketch_quality=quality,body_count=len(bodies),
            volume_mm3=sum(automation._body_mass_props(b,'mm')['volume_exact'] for b in bodies),
            preview_paths=export_scene_views(automation,doc,output.parent),visual_approximation=True)
        (output.parent/'reference-native.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
