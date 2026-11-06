"""Native associative Hole Wizard patterns, with independent B-Rep checks.

Native selectors reuse the MIT sw_pattern adapter. Mirror selection follows
czuryk/SolidworksMCP more_features.py (plane=2, features=1), not UI selection.
"""
from __future__ import annotations
import math
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class HolePattern(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    kind:Literal['linear','circular','mirror']
    seed_hole_index:int=Field(ge=0,le=11,description='Zero-based index in this part standard_holes list.')
    count:int=Field(default=2,ge=2,le=32,description='Includes the original seed; mirror always has two.')
    direction:Literal['+x','-x','+y','-y']='+x'
    spacing_mm:float|None=Field(default=None,gt=0,le=2000)
    second_direction:Literal['+x','-x','+y','-y']|None=None
    second_count:int=Field(default=1,ge=1,le=32)
    second_spacing_mm:float|None=Field(default=None,gt=0,le=2000)
    center_mm:list[float]|None=Field(default=None,min_length=2,max_length=2,description='XY axis center; circular patterns need an existing unique Z-cylinder there.')
    mirror_plane:Literal['XZ','YZ']='YZ'
    @model_validator(mode='after')
    def valid(self):
        if self.count*self.second_count>64:raise ValueError('At most 64 pattern instances')
        if self.kind=='linear':
            if self.spacing_mm is None or self.center_mm is not None:raise ValueError('Linear pattern requires spacing and no circular center')
            if self.second_count>1 and (self.second_direction is None or self.second_spacing_mm is None or self.direction[-1]==self.second_direction[-1]):raise ValueError('Grid needs perpendicular directions and both spacings')
            if self.second_count==1 and (self.second_direction is not None or self.second_spacing_mm is not None):raise ValueError('Unused second pattern direction')
        elif self.spacing_mm is not None or self.second_count!=1 or self.second_direction is not None or self.second_spacing_mm is not None:raise ValueError('Unexpected linear pattern parameters')
        if self.kind=='circular':
            if self.center_mm is None or any(not math.isfinite(v) or abs(v)>2000 for v in self.center_mm):raise ValueError('Circular pattern requires a finite XY center')
        elif self.center_mm is not None:raise ValueError('Unexpected circular center')
        if self.kind=='mirror' and self.count!=2:raise ValueError('A mirror has exactly seed and copy')
        return self
    def points(self,seed):
        x,y,z=seed
        if self.kind=='mirror':
            return [list(seed),[-x,y,z] if self.mirror_plane=='YZ' else [x,-y,z]]
        if self.kind=='circular':
            cx,cy=self.center_mm
            if math.hypot(x-cx,y-cy)<1e-4:raise ValueError('Circular seed cannot be on its own axis')
            return [[cx+(x-cx)*math.cos(a)-(y-cy)*math.sin(a),cy+(x-cx)*math.sin(a)+(y-cy)*math.cos(a),z] for a in [2*math.pi*i/self.count for i in range(self.count)]]
        def offset(d,s):return [(-1 if d[0]=='-' else 1)*s if d[-1]=='x' else 0,(-1 if d[0]=='-' else 1)*s if d[-1]=='y' else 0]
        first=offset(self.direction,self.spacing_mm);second=offset(self.second_direction,self.second_spacing_mm) if self.second_count>1 else [0,0]
        return [[x+i*first[0]+j*second[0],y+i*first[1]+j*second[1],z] for j in range(self.second_count) for i in range(self.count)]

def validate_patterns(holes,operations):
    points=[h.point_mm for h in holes]
    for op in operations:
        if op.seed_hole_index>=len(holes):raise ValueError('Pattern seed is not in standard_holes')
        seed=holes[op.seed_hole_index]
        if seed.outward!='+z' or seed.kind=='tapped' or seed.thread_representation=='modeled':raise ValueError('This qualified pattern route supports local +Z clearance/counterbore/countersink holes, not tapped/modeled threads')
        made=op.points(seed.point_mm)
        for point in made[1:]:
            if any(math.dist(point,p)<1e-4 for p in points):raise ValueError('Pattern would duplicate an existing hole or another instance')
            points.append(point)
        if len(points)>128:raise ValueError('Pattern hole budget exceeds 128')
    return points

def cylinders(doc):
    """Read inward Z-cylinder axes/radii and exact circular end sections."""
    from scripts.sw_connect import get_com_member as get
    rows=[]
    for body in get(doc,'GetBodies2',0,False) or []:
        for face in get(body,'GetFaces') or []:
            surface=get(face,'GetSurface')
            if not get(surface,'IsCylinder'):continue
            cp=list(get(surface,'CylinderParams'))
            if abs(abs(cp[5])-1)>1e-7:continue
            ends=[];sample=None
            for edge in get(face,'GetEdges') or []:
                curve=get(edge,'GetCurve')
                if not get(curve,'IsCircle'):continue
                circle=list(get(curve,'CircleParams'));ends.append(circle[2]*1000)
                sample=list(get(edge,'GetCurveParams2'))[:3]
            if not ends or sample is None:continue
            normal=list(get(surface,'EvaluateAtPoint',*sample))[:3];sense=-1 if get(face,'FaceInSurfaceSense') else 1
            if sum(normal[i]*(sample[i]-cp[i]) for i in (0,1))*sense>=0:continue
            rows.append({'x':cp[0]*1000,'y':cp[1]*1000,'radius_mm':cp[6]*1000,'z_min_mm':min(ends),'z_max_mm':max(ends)})
    return rows

def same(a,b):return all(math.isclose(a[k],b[k],abs_tol=1e-4) for k in ('x','y','radius_mm','z_min_mm','z_max_mm'))

def geometry(doc,record,actual_cylinders=None):
    actual=cylinders(doc) if actual_cylinders is None else actual_cylinders;wanted=record['expected_cylinders']
    matched=all(sum(same(w,a) for a in actual)==1 for w in wanted)
    return {'passed':matched,'expected_cylinders':wanted,'matched_cylinder_count':sum(any(same(w,a) for a in actual) for w in wanted),'source':'native inward cylindrical B-Rep faces'}

def read(doc,record,actual_cylinders=None):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    op=HolePattern.model_validate(record['operation']);feature=doc.FeatureByName(record['feature'])
    if feature is None:raise RuntimeError('Associative hole pattern disappeared')
    data=typed(get(feature,'GetDefinition'),{'linear':'ILinearPatternFeatureData','circular':'ICircularPatternFeatureData','mirror':'IMirrorPatternFeatureData'}[op.kind])
    if not data.AccessSelections(doc,None):raise RuntimeError('Cannot access native pattern definition')
    try:
        seeds=list(get(data,'PatternFeatureArray') or []);names=[str(get(f,'Name')) for f in seeds]
        native={'feature':record['feature'],'type':str(get(feature,'GetTypeName2')),'seed_features':names}
        ok=names==[record['seed_feature']]
        if op.kind=='linear':
            native.update(count=int(get(data,'D1TotalInstances')),spacing_mm=float(get(data,'D1Spacing'))*1000,second_count=int(get(data,'D2TotalInstances')),second_spacing_mm=float(get(data,'D2Spacing'))*1000)
            ok=ok and native['count']==op.count and math.isclose(native['spacing_mm'],op.spacing_mm,abs_tol=1e-5) and native['second_count']==op.second_count
            if op.second_count>1:ok=ok and math.isclose(native['second_spacing_mm'],op.second_spacing_mm,abs_tol=1e-5)
        elif op.kind=='circular':
            native.update(count=int(get(data,'TotalInstances')),spacing_rad=float(get(data,'Spacing')),equal_spacing=bool(get(data,'EqualSpacing')))
            ok=ok and native['count']==op.count and native['equal_spacing']
        else:native['mirror_plane']=op.mirror_plane
    finally:data.ReleaseSelectionAccess()
    actual=geometry(doc,record,actual_cylinders);native['geometry']=actual;native['passed']=bool(ok and actual['passed'])
    if not native['passed']:raise RuntimeError('Native pattern parameters or actual hole positions differ from the request')
    return native

def apply(app,doc,operations,holes):
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_pattern import linear_pattern,circular_pattern
    from scripts.sw_part import _select_by_id,_get_plane_name_candidates
    from solidworks_mcp.automation.com_utils import typed
    def volume():return sum(float(list(get(b,'GetMassProperties',1000.))[3])*1e9 for b in get(doc,'GetBodies2',0,False) or [])
    def vector(direction):return [(-1 if direction[0]=='-' else 1) if direction[-1]==axis else 0 for axis in ('x','y','z')]
    results=[]
    for i,op in enumerate(operations):
        source=holes[op.seed_hole_index];point=source['operation']['point_mm'];seed=source['native']['feature'];before=cylinders(doc)
        prototypes=[r for r in before if math.hypot(r['x']-point[0],r['y']-point[1])<1e-4]
        if not prototypes:raise ValueError('Pattern seed has no measurable inward cylindrical geometry')
        targets=op.points(point)[1:];expected=[{**r,'x':p[0],'y':p[1]} for p in targets for r in prototypes]
        if any(any(same(e,a) for a in before) for e in expected):raise ValueError('Pattern target geometry already exists')
        initial=volume();wanted=initial-len(targets)*source['removed_volume_mm3']
        if wanted<=0:raise ValueError('Pattern cannot remove the entire part')
        doc.ClearSelection2(True)
        try:
            if op.kind=='linear':feature=linear_pattern(doc,seed,vector(op.direction),op.spacing_mm/1000,op.count,vector(op.second_direction) if op.second_count>1 else (0,0,0),(op.second_spacing_mm or 0)/1000,op.second_count)
            elif op.kind=='circular':
                candidates=[]
                for body in get(doc,'GetBodies2',0,False) or []:
                    for face in get(body,'GetFaces') or []:
                        surface=get(face,'GetSurface')
                        if not get(surface,'IsCylinder'):continue
                        cp=list(get(surface,'CylinderParams'))
                        if abs(abs(cp[5])-1)<1e-7 and math.dist([v*1000 for v in cp[:2]],op.center_mm)<1e-4:candidates.append(face)
                if len(candidates)!=1:raise ValueError('Circular pattern requires one unique native cylindrical face on its exact axis')
                feature=circular_pattern(doc,seed,candidates[0],2*math.pi,op.count,True)
            else:
                if not doc.FeatureByName(seed).Select2(False,1):raise RuntimeError('Cannot select mirror seed')
                plane={'XZ':'Top Plane','YZ':'Right Plane'}[op.mirror_plane]
                if not any(_select_by_id(doc.Extension,n,'PLANE',True,2) for n in _get_plane_name_candidates(plane)):raise RuntimeError('Cannot select native mirror plane')
                feature=typed(doc.FeatureManager,'IFeatureManager').InsertMirrorFeature2(False,False,False,False,0)
            if feature is None:raise RuntimeError('Native associative pattern creation failed; no manual copies substituted')
            feature.Name='AI_HolePattern_'+str(i+1)
            if not get(doc,'ForceRebuild3',False):raise RuntimeError('Pattern rebuild failed')
            record={'operation':op.model_dump(),'feature':str(get(feature,'Name')),'seed_feature':seed,'expected_cylinders':expected,'expected_volume_mm3':wanted,'before_volume_mm3':initial}
            after=cylinders(doc);record['native']=read(doc,record,after);actual=volume()
            if len(list(get(doc,'GetBodies2',0,False) or []))!=1 or not math.isclose(actual,wanted,rel_tol=1e-7,abs_tol=.001):raise RuntimeError('Pattern material removal differs from complete non-overlapping seed copies')
            if len(after)!=len(before)+len(expected) or not all(any(same(a,b) for b in after) for a in before):raise RuntimeError('Pattern changed unrequested hole geometry')
            record['volume_mm3']=actual;record['unrequested_holes_preserved']=True;results.append(record)
        finally:doc.ClearSelection2(True)
    return results
