"""Native analytic silhouette intersections and axis-aware cylindrical/cone cuts."""
from __future__ import annotations
import math,sys
from shapely.geometry import Polygon,LineString,Point
from shapely.ops import unary_union,polygonize
from .native_advanced import _get,_sketch,_depth
from .analytic import AXES,contour_polygon

def _plane(doc,axis,value,name):
    from scripts.sw_part import _select_first_candidate,_get_plane_name_candidates
    from integrations.czuryk.loft_native import _last_feature
    from solidworks_mcp.automation.com_utils import resolve_solidworks_constant as constant
    base={2:'Front Plane',1:'Top Plane',0:'Right Plane'}[axis]
    if abs(value)<1e-8:return base
    doc.ClearSelection2(True)
    if not _select_first_candidate(doc.Extension,_get_plane_name_candidates(base),'PLANE'):raise RuntimeError('Native reference plane unavailable')
    constraint=constant('swRefPlaneReferenceConstraint_Distance')
    if value<0:constraint|=constant('swRefPlaneReferenceConstraint_OptionFlip')
    if doc.FeatureManager.InsertRefPlane(constraint,abs(value)/1000,0,0.,0,0.) is None:raise RuntimeError('Signed native offset plane failed')
    plane=_last_feature(doc,'RefPlane');plane.Name=name;return name

def _transform(app,sketch,p):
    from solidworks_mcp.automation.com_utils import typed,array_r8
    utility=typed(_get(app,'GetMathUtility'),'IMathUtility');point=utility.CreatePoint(array_r8([x/1000 for x in p]))
    return [float(x)*1000 for x in _get(point.MultiplyTransform(_get(sketch,'ModelToSketchTransform')),'ArrayData')]

def _world_sketch(doc,loops,a,axes,fixed,name):
    u,v=axes;normal=next(i for i in range(3) if i not in axes);plane=_plane(doc,normal,fixed,name)
    def mapper(items):
        sketch=_get(doc,'GetActiveSketch2')
        def point(p):
            q=[0.,0.,0.];q[u],q[v],q[normal]=p[0],p[1],fixed
            local=_transform(a.app,sketch,q)
            if abs(local[2])>1e-4:raise RuntimeError('Native plane transform does not contain requested geometry')
            return local[:2]
        origin=point([0,0]);du=point([1,0]);dv=point([0,1]);det=(du[0]-origin[0])*(dv[1]-origin[1])-(du[1]-origin[1])*(dv[0]-origin[0])
        result=[]
        for loop in items:
            out=[]
            for s in loop:
                s=dict(s)
                for key in ('start','end','center'):
                    if key in s:s[key]=point(s[key])
                if s['kind']=='arc' and det<0:s['ccw']=not s['ccw']
                out.append(s)
            result.append(out)
        return result
    return _sketch(doc,loops,a,plane,coordinate_map=mapper)

def _shift(profile,offset):
    out=[]
    for s in profile:
        s=dict(s)
        for key in ('start','end','center'):
            if key in s:s[key]=[s[key][0]-offset[0],s[key][1]-offset[1]]
        out.append(s)
    return out

def read_feature(feature,record):
    if record.get('operation')!='revolve':return {**record,**_depth(feature,record['depth_mm'] or 0,record['through_all'])}
    definition=_get(feature,'GetDefinition');angle=float(_get(definition,'GetRevolutionAngle',True))
    kind=str(_get(feature,'GetTypeName2'))
    if abs(angle-math.tau)>1e-7 or kind!='RevCut':raise RuntimeError('Native cut-revolve angle/type readback failed')
    return {**record,'feature':str(_get(feature,'Name')),'type':kind,'angle_rad':angle,'definition_readback':True}

def _cone(doc,a,h,radius0,radius1,start,depth,label):
    from .native_advanced import _segments
    from scripts.sw_part import _ensure_sketch_selected
    axis=h['axis_index'];radial=0 if axis!=0 else 1;normal=next(i for i in range(3) if i not in (radial,axis));p=h['entry_mm'];sign=h['direction'][axis]
    t0=p[axis]+sign*start;t1=p[axis]+sign*(start+depth);c=p[radial]
    points=[[c,t0],[c+radius0,t0],[c+radius1,t1],[c,t1]] if radius1>0 else [[c,t0],[c+radius0,t0],[c,t1]]
    ref=_world_sketch(doc,[_segments(points)],a,(radial,axis),p[normal],h['id']+'_'+label+'Plane')
    _ensure_sketch_selected(doc,ref);selection=_get(doc.SelectionManager,'CreateSelectData');selection.Mark=16
    if not ref.segments[-1].Select4(True,selection):raise RuntimeError('Native cone revolve axis selection failed')
    feature=doc.FeatureManager.FeatureRevolve2(True,True,False,True,False,False,0,0,math.tau,0.,False,False,0.,0.,0,0.,0.,True,True,True)
    if feature is None:raise RuntimeError('Native cut-revolve failed: '+h['id'])
    feature.Name=h['id']+'_'+label
    return read_feature(feature,{'feature':str(feature.Name),'operation':'revolve','angle_rad':math.tau})

def _entry_face(a,doc,h):
    p=h['entry_mm'];axis=h['axis_index'];matches=[]
    for body in a._get_solid_bodies(doc):
        for face in _get(body,'GetFaces') or []:
            surface=_get(face,'GetSurface')
            if not _get(surface,'IsPlane'):continue
            plane=list(_get(surface,'PlaneParams'))
            if abs(abs(plane[axis])-1)>1e-6:continue
            closest=list(_get(face,'GetClosestPointOn',*[x/1000 for x in p]))
            if math.dist([x*1000 for x in closest[:3]],p)<1e-4:matches.append(face)
    if len(matches)!=1:raise RuntimeError('Hole entry must be on one actual native planar face: '+h['id'])

def create_part(app,a,spec):
    from scripts.sw_part import extrude_boss,extrude_cut,_ensure_sketch_selected
    from .parser import signed_area
    if not a.create_new_part().get('success'):raise RuntimeError('Cannot create analytic native part')
    doc=app.ActiveDoc;L,W,H=spec['size_mm'];features=[];offsets={'top':[L/2,W/2],'front':[L/2,0],'right':[W/2,0]}
    ref=_world_sketch(doc,[_shift(spec['profiles']['top'],offsets['top'])],a,(0,1),0,'BasePlane')
    feature=extrude_boss(doc,ref,H/1000,direction=False)
    if feature is None:raise RuntimeError('Native analytical top prism failed')
    feature.Name='AnalyticalBase';features.append({'feature':str(feature.Name),'operation':'exact_profile_extrusion'})
    for role,area in [('front',L*H),('right',W*H)]:
        profile=spec['profiles'][role]
        if abs(abs(signed_area(profile))-area)<1e-7:continue
        print('Native analytical silhouette intersection',role,flush=True,file=sys.stderr)
        ref=_world_sketch(doc,[_shift(profile,offsets[role])],a,AXES[role],0,role+'SilhouettePlane')
        _ensure_sketch_selected(doc,ref)
        cut=doc.FeatureManager.FeatureCut4(False,True,False,1,1,.01,.01,False,False,False,False,0.,0.,False,False,False,False,False,True,True,False,False,False,0,0.,False,False)
        if cut is None:raise RuntimeError('Native two-direction outside silhouette cut failed: '+role)
        cut.Name=role.title()+'SilhouetteIntersection';features.append({'feature':str(cut.Name),'operation':'outside_cut_through_all_both_directions'})
    if len(a._get_solid_bodies(doc))!=1:raise RuntimeError('Silhouette intersection must yield one solid')
    for h in spec['holes']:
        print('Native analytical hole',h['id'],h['axis'],h['kind'],flush=True,file=sys.stderr)
        _entry_face(a,doc,h);axis=h['axis_index'];axes=tuple(i for i in range(3) if i!=axis);p=h['entry_mm'];h['native_features']=[]
        operations=[('Base',h['radius_mm'],h['cut_depth_mm'],h['through'])]
        if h['counterbore_radius_mm'] is not None and not h['countersink_angle_deg']:operations.append(('Recess',h['counterbore_radius_mm'],h['counterbore_depth_mm'],False))
        for label,radius,depth,through in operations:
            ref=_world_sketch(doc,[[{'kind':'circle','center':[p[i] for i in axes],'radius':radius}]],a,axes,p[axis],h['id']+'_EntryPlane'+label)
            local0=_transform(app,ref.sketch,p);q=[x+d for x,d in zip(p,h['direction'])];local1=_transform(app,ref.sketch,q)
            direction=local1[2]>local0[2]
            feature=extrude_cut(doc,ref,0 if through else depth/1000,direction=direction)
            if feature is None:raise RuntimeError('Native axis-aware hole cut failed: '+h['id'])
            feature.Name=h['id']+'_'+label;h['native_features'].append({**_depth(feature,depth,through),'operation':'extrude','direction_reversed':direction})
        if h['drill_point_height_mm']:h['native_features'].append(_cone(doc,a,h,h['radius_mm'],0,h['cut_depth_mm'],h['drill_point_height_mm'],'DrillPoint'))
        if h['countersink_angle_deg']:h['native_features'].append(_cone(doc,a,h,h['counterbore_radius_mm'],h['radius_mm'],0,h['counterbore_depth_mm'],'Countersink'))
    if not _get(doc,'ForceRebuild3',False):raise RuntimeError('Native analytical part rebuild failed')
    return doc,features

def _edge_points(edge):
    from solidworks_mcp.automation.com_utils import typed
    curve=_get(edge,'GetCurve');start,end=_get(edge,'GetStartVertex'),_get(edge,'GetEndVertex')
    if _get(curve,'IsLine') and start is not None and end is not None:return [[v*1000 for v in _get(obj,'GetPoint')] for obj in (start,end)]
    params=list(_get(edge,'GetCurveParams2'));lo,hi=params[6:8]
    native_edge=typed(edge,'IEdge')
    if native_edge is None:raise RuntimeError('Typed native edge interface unavailable')
    def evaluate(t,n=0):
        import struct
        values=list(native_edge.Evaluate2(t,n))
        if len(values)!=(n+1)*3+1 or struct.unpack('<ii',struct.pack('<d',values[-1]))[0]!=1:raise RuntimeError('Native edge evaluation failed')
        return values[:-1]
    first,last=evaluate(lo),evaluate(hi)
    if math.dist(first[:3],params[:3])>1e-7 or math.dist(last[:3],params[3:6])>1e-7:raise RuntimeError('Native edge parameter range does not match endpoints')
    if _get(curve,'IsCircle'):
        c=list(_get(curve,'CircleParams'));center=[x*1000 for x in c[:3]];radius=c[6]*1000
        evaluated=evaluate(lo,1);p=[x*1000 for x in evaluated[:3]];tangent=evaluated[3:6];length=math.sqrt(sum(x*x for x in tangent))
        u=[(x-y)/radius for x,y in zip(p,center)];v=[x/length for x in tangent]
        count=max(8,math.ceil(abs(hi-lo)/(2*math.acos(max(-1,1-.002/radius)))))
        angles={(hi-lo)*i/count for i in range(count+1)}
        for j in range(3):
            critical=math.atan2(v[j],u[j])
            for k in range(-4,5):
                t=critical+k*math.pi
                if 0<t<hi-lo:angles.add(t)
        points=[[center[j]+radius*(u[j]*math.cos(t)+v[j]*math.sin(t)) for j in range(3)] for t in sorted(angles)]
        if math.dist(points[0],[v*1000 for v in first[:3]])>1e-4 or math.dist(points[-1],[v*1000 for v in last[:3]])>1e-4:raise RuntimeError('Native circular edge angular span does not match endpoints')
        return points
    def at(t):return [float(v)*1000 for v in evaluate(t)[:3]]
    def subdiv(a,b,pa,pb,level):
        m=(a+b)/2;pm=at(m);chord=[(x+y)/2 for x,y in zip(pa,pb)]
        if math.dist(pm,chord)<.002:return [pa,pb]
        if level<=0:raise RuntimeError('Native edge verification sampling did not converge')
        return subdiv(a,m,pa,pm,level-1)[:-1]+subdiv(m,b,pm,pb,level-1)
    # Split full circles up front; midpoint alone can miss an entire turn.
    out=[]
    for i in range(8):
        a=lo+(hi-lo)*i/8;b=lo+(hi-lo)*(i+1)/8;out+=subdiv(a,b,at(a),at(b),16)[:-1]
    return out+[at(hi)]

def _projections(faces,spec):
    L,W,_=spec['size_mm'];offset=[L/2,W/2,0];records={}
    for role,(u,v) in AXES.items():
        lines=[]
        for edges in faces:
            for points in edges:
                pts=[[round(p[u],7),round(p[v],7)] for p in points]
                line=LineString(pts)
                if line.length>1e-6:lines.append(line)
        regions=list(polygonize(unary_union(lines)))
        actual=unary_union(regions)
        if actual.is_empty:raise RuntimeError('Native projected topology is empty: '+role)
        # Fill hole loops when comparing the outside silhouette, not feature holes.
        polys=list(actual.geoms) if actual.geom_type=='MultiPolygon' else [actual]
        exterior=unary_union([Polygon(p.exterior) for p in polys])
        expected=contour_polygon(_shift(spec['profiles'][role],[offset[u],offset[v]]));error=exterior.symmetric_difference(expected).area;hausdorff=exterior.hausdorff_distance(expected)
        network=unary_union(lines).buffer(.015);missing=0.
        from .parser import samples
        for s in spec.get('detail_curves',{}).get(role,[]):missing+=LineString([[p[0]-offset[u],p[1]-offset[v]] for p in samples(s)]).difference(network).length
        records[role]={'passed':hausdorff<.025 and error<.025*expected.length and missing<.02,'difference_area_mm2':error,'hausdorff_mm':hausdorff,'unmatched_detail_length_mm':missing,'verification_chord_tolerance_mm':.002,'method':'native B-Rep edge evaluation; sampled only for projection verification; exact native CAD retained'}
    return {'passed':all(v['passed'] for v in records.values()),'views':records}

def measure(a,doc,spec):
    from engineering.native import _exact_bounds
    bodies=a._get_solid_bodies(doc);volume=sum(a._body_mass_props(b,'mm')['volume_exact'] for b in bodies);bounds=_exact_bounds(bodies);cylinders=[];cones=[];disks=[];faces=[]
    for body in bodies:
        for face in _get(body,'GetFaces') or []:
            surface=_get(face,'GetSurface');circles=[];vertices=[];edges=[]
            for edge in _get(face,'GetEdges') or []:
                curve=_get(edge,'GetCurve');edges.append(_edge_points(edge))
                if _get(curve,'IsCircle'):
                    c=list(_get(curve,'CircleParams'));circles.append({'center_mm':[v*1000 for v in c[:3]],'radius_mm':c[6]*1000})
                for vertex in (_get(edge,'GetStartVertex'),_get(edge,'GetEndVertex')):
                    if vertex is not None:vertices.append([v*1000 for v in _get(vertex,'GetPoint')])
            faces.append(edges)
            if _get(surface,'IsCylinder'):
                c=list(_get(surface,'CylinderParams'));cylinders.append({'point':[v*1000 for v in c[:3]],'direction':c[3:6],'radius':c[6]*1000,'circles':circles})
                # A smooth cylinder silhouette may have no topological edge at
                # its tangent generator. Derive it from the actual analytic
                # surface and require points to lie on the trimmed native face.
                if len(circles)>=2:
                    axis=max(range(3),key=lambda i:abs(c[3+i]))
                    if abs(abs(c[3+axis])-1)<1e-6:
                        low=min(q['center_mm'][axis] for q in circles);high=max(q['center_mm'][axis] for q in circles)
                        for radial in (i for i in range(3) if i!=axis):
                            for sign in (-1,1):
                                p=[v*1000 for v in c[:3]];p[radial]+=sign*c[6]*1000;points=[];valid=True
                                for t in (low,(low+high)/2,high):
                                    p=list(p);p[axis]=t;closest=list(_get(face,'GetClosestPointOn',*[v/1000 for v in p]))
                                    if math.dist([v*1000 for v in closest[:3]],p)>1e-4:valid=False;break
                                    points.append(p)
                                if valid:faces.append([points])
            elif _get(surface,'IsCone'):
                c=list(_get(surface,'ConeParams2'));cones.append({'point':[v*1000 for v in c[:3]],'direction':c[3:6],'half_angle_rad':c[7],'circles':circles,'vertices':vertices,'face':face})
            elif _get(surface,'IsPlane') and len(circles)==1 and len(edges)==1:disks+=circles
    evidence=[]
    for h in spec['holes']:
        axis=h['axis_index'];p=h['entry_mm'];sign=h['direction'][axis];r=h['radius_mm'];R=h['counterbore_radius_mm'];recess=h['counterbore_depth_mm'] or 0.;d=h['cut_depth_mm'];tip=h['drill_point_height_mm']
        def center_ok(q):return all(abs(q[i]-p[i])<1e-4 for i in range(3) if i!=axis)
        def t(q):return (q[axis]-p[axis])*sign
        expected=[(r,recess,d)]
        if R is not None and not h['countersink_angle_deg']:expected.append((R,0,recess))
        cylinders_ok=[]
        for radius,lo,hi in expected:
            cylinders_ok.append(any(abs(abs(c['direction'][axis])-1)<1e-6 and center_ok(c['point']) and abs(c['radius']-radius)<1e-4 and len(c['circles'])>=2 and abs(min(t(q['center_mm']) for q in c['circles'])-lo)<1e-4 and abs(max(t(q['center_mm']) for q in c['circles'])-hi)<1e-4 for c in cylinders))
        cone_checks=[]
        for angle,lo,hi,large,small in [(h['drill_point_angle_deg'],d,d+tip,r,0),(h['countersink_angle_deg'],0,recess,R,r)]:
            if angle is None:continue
            match=False
            for c in cones:
                if abs(abs(c['direction'][axis])-1)>1e-6 or not center_ok(c['point']) or abs(abs(c['half_angle_rad'])-math.radians(angle)/2)>1e-6:continue
                circles=c['circles'];upper=any(center_ok(q['center_mm']) and abs(q['radius_mm']-large)<1e-4 and abs(t(q['center_mm'])-lo)<1e-4 for q in circles)
                if small:lower=any(center_ok(q['center_mm']) and abs(q['radius_mm']-small)<1e-4 and abs(t(q['center_mm'])-hi)<1e-4 for q in circles)
                else:
                    apex=[x+d*hi for x,d in zip(p,h['direction'])]
                    closest=list(_get(c['face'],'GetClosestPointOn',*[x/1000 for x in apex]))
                    lower=math.dist([x*1000 for x in closest[:3]],apex)<1e-4
                match=match or (upper and lower)
            cone_checks.append({'included_angle_deg':angle,'axial_interval_mm':[lo,hi],'large_radius_mm':large,'small_radius_mm':small,'native_cone_verified':match})
        bottom=any(center_ok(q['center_mm']) and abs(t(q['center_mm'])-d)<1e-4 and abs(q['radius_mm']-r)<1e-4 for q in disks)
        terminal_ok=not bottom if h['through'] or tip else bottom
        evidence.append({'id':h['id'],'kind':h['kind'],'axis':h['axis'],'entry_mm':p,'cylinder_intervals_verified':all(cylinders_ok),'expected_cylinder_intervals_mm':expected,'cones':cone_checks,'flat_bottom_disk_present':bottom,'terminal_verified':terminal_ok,'native_features':h['native_features'],'passed':all(cylinders_ok) and terminal_ok and all(c['native_cone_verified'] for c in cone_checks)})
    projections=_projections(faces,spec);size_ok=all(abs(x-y)<1e-4 for x,y in zip(bounds['size_mm'],spec['size_mm']));volume_ok=math.isclose(volume,spec['expected_volume_mm3'],rel_tol=1e-6,abs_tol=.002)
    return {'passed':len(bodies)==1 and size_ok and volume_ok and projections['passed'] and all(h['passed'] for h in evidence),'body_count':len(bodies),'volume_mm3':volume,'expected_volume_mm3':spec['expected_volume_mm3'],'exact_bounds':bounds,'size_verified':size_ok,'volume_verified':volume_ok,'holes':evidence,'native_projections':projections,'volume_method':spec['volume_method'],'native_cone_count':len(cones)}
