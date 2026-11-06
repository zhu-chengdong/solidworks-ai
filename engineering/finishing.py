"""Native bounded edge treatments selected from live B-Rep, never edge names."""
from __future__ import annotations
import math
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class EdgeTreatment(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    kind:Literal['fillet','chamfer']
    target:Literal['vertical_edges','top_outer','bottom_outer','hole_mouth']
    size_mm:float=Field(gt=0,le=100)
    angle_deg:float=Field(default=45,gt=0,lt=90)
    expected_edges:int=Field(ge=1,le=100)
    hole_center_mm:list[float]|None=Field(default=None,min_length=3,max_length=3)
    hole_radius_mm:float|None=Field(default=None,gt=0,le=500)
    @model_validator(mode='after')
    def valid(self):
        if self.target=='hole_mouth' and (self.hole_center_mm is None or self.hole_radius_mm is None):raise ValueError('Hole mouth needs an exact center and radius')
        if self.target!='hole_mouth' and (self.hole_center_mm is not None or self.hole_radius_mm is not None):raise ValueError('Unexpected hole selection')
        if self.hole_center_mm and any(not math.isfinite(v) or abs(v)>2000 for v in self.hole_center_mm):raise ValueError('Invalid mouth center')
        return self

def select(doc,op):
    from scripts.sw_connect import get_com_member as get,create_empty_dispatch_variant
    from solidworks_mcp.automation.com_utils import typed
    from engineering.native import _exact_bounds
    bodies=list(get(doc,'GetBodies2',0,False) or [])
    if len(bodies)!=1:raise ValueError('Edge treatments currently require one solid body')
    bound=_exact_bounds(bodies);chosen=[]
    if op.target in {'top_outer','bottom_outer'}:
        z=bound['max' if op.target=='top_outer' else 'min'][2]/1000
        faces=[]
        for face in get(bodies[0],'GetFaces') or []:
            surface=get(face,'GetSurface')
            if not get(surface,'IsPlane'):continue
            params=list(get(surface,'PlaneParams'))
            if abs(abs(params[2])-1)>1e-7 or abs(params[5]-z)>1e-7:continue
            faces.append(face)
        if len(faces)!=1:raise ValueError('Outer planar boundary is missing or ambiguous')
        for loop in get(faces[0],'GetLoops') or []:
            if get(loop,'IsOuter'):chosen+=list(get(loop,'GetEdges') or [])
    else:
        for edge in get(bodies[0],'GetEdges') or []:
            curve=get(edge,'GetCurve')
            if op.target=='vertical_edges':
                if not get(curve,'IsLine'):continue
                a=get(get(edge,'GetStartVertex'),'GetPoint');b=get(get(edge,'GetEndVertex'),'GetPoint')
                if abs(a[0]-b[0])>1e-8 or abs(a[1]-b[1])>1e-8 or abs(a[2]-b[2])<1e-8:continue
            else:
                if not get(curve,'IsCircle'):continue
                circle=list(get(curve,'CircleParams'))
                if math.dist([v*1000 for v in circle[:3]],op.hole_center_mm)>1e-4 or abs(circle[6]*1000-op.hole_radius_mm)>1e-4:continue
            chosen.append(edge)
    if len(chosen)!=op.expected_edges:raise ValueError(f'Edge selection count differs: expected {op.expected_edges}, got {len(chosen)}; no treatment executed')
    doc.ClearSelection2(True);signatures=[]
    try:
        for edge in chosen:
            native=typed(edge,'IEdge');curve=typed(get(edge,'GetCurve'),'ICurve')
            signature={'circle':bool(get(curve,'IsCircle'))}
            if signature['circle']:
                signature['circle_params']=list(get(curve,'CircleParams'));parameters=list(get(edge,'GetCurveParams2'))
                signature['length_mm']=abs(parameters[7]-parameters[6])*signature['circle_params'][6]*1000
            else:
                signature['endpoints_mm']=[[v*1000 for v in get(get(edge,n),'GetPoint')] for n in ('GetStartVertex','GetEndVertex')]
                signature['length_mm']=math.dist(*signature['endpoints_mm'])
            signatures.append(signature)
            if not edge.Select4(True,create_empty_dispatch_variant()):raise RuntimeError('Native edge selection failed')
    except BaseException:doc.ClearSelection2(True);raise
    return signatures

def read(doc,name,op):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    feature=doc.FeatureByName(name)
    if feature is None:raise RuntimeError('Treatment feature disappeared')
    kind=str(get(feature,'GetTypeName2'))
    data=typed(get(feature,'GetDefinition'),'ISimpleFilletFeatureData2' if op.kind=='fillet' else 'IChamferFeatureData2')
    if data is None:raise RuntimeError('Treatment definition unavailable')
    evidence={'feature':name,'type':kind,'kind':op.kind}
    access=bool(data.AccessSelections(doc,None))
    if not access:raise RuntimeError('Treatment selection access unavailable')
    try:
        size=float(get(data,'DefaultRadius'))*1000 if op.kind=='fillet' else float(data.GetEdgeChamferDistance(0))*1000
        evidence['size_mm']=size;evidence['passed']=math.isclose(size,op.size_mm,abs_tol=1e-5)
        if op.kind=='fillet':evidence['edge_count']=int(get(data,'GetEdgeCount'));evidence['passed'] &= kind=='Fillet' and evidence['edge_count']==op.expected_edges
        else:
            evidence['angle_deg']=math.degrees(float(get(data,'EdgeChamferAngle')))
            evidence['edge_count']=int(get(data,'GetEdgeCount'))
            evidence['passed'] &= kind=='Chamfer' and math.isclose(evidence['angle_deg'],op.angle_deg,abs_tol=1e-5) and evidence['edge_count']==op.expected_edges
    finally:data.ReleaseSelectionAccess()
    if not evidence['passed']:raise RuntimeError('Treatment readback differs from the requested parameters')
    return evidence

def apply(doc,operations):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    results=[]
    for i,op in enumerate(operations):
        signatures=select(doc,op)
        try:
            fm=typed(doc.FeatureManager,'IFeatureManager')
            feature=fm.FeatureFillet(195,op.size_mm/1000,0.,0.) if op.kind=='fillet' else fm.InsertFeatureChamfer(4,1,op.size_mm/1000,math.radians(op.angle_deg),0.,0.,0.,0.)
            if feature is None:raise RuntimeError('Native edge treatment failed; requested dimensions were not reduced')
            feature.Name='AI_'+op.kind+'_'+str(i+1)
            if not get(doc,'ForceRebuild3',False):raise RuntimeError('Treatment did not rebuild')
        finally:doc.ClearSelection2(True)
        evidence=read(doc,str(get(feature,'Name')),op);results.append({'operation':op.model_dump(),'selection':signatures,'native':evidence})
    return results
