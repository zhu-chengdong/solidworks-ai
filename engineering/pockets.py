"""Native editable planar cuts with independent profile/depth B-Rep checks.

Slot API checked against the installed 2024 type library. API construction
reference: MIT hjbaard/SolidWorks-MCP, session._sketch_slot; see existing notice.
Copyright (c) 2026 Henk Jan Baard. See release_tools/licenses/HJBAARD-MIT.txt.
"""
from __future__ import annotations
import math,struct
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class PlanarCut(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    kind:Literal['slot','pocket']
    z_mm:float=Field(ge=-2000,le=2000,description='Exact local +Z entry plane; initial scope is the highest planar stock face.')
    depth_mm:float|None=Field(default=None,gt=0,le=500,description='None means true Through All; otherwise flat-bottom blind depth.')
    center_mm:list[float]|None=Field(default=None,min_length=2,max_length=2)
    length_mm:float|None=Field(default=None,gt=0,le=2000,description='Slot overall end-to-end length, including both round ends.')
    width_mm:float|None=Field(default=None,gt=0,le=1000)
    angle_deg:float=Field(default=0,ge=-180,le=180)
    points_mm:list[Annotated[list[float],Field(min_length=2,max_length=2)]]|None=Field(default=None,min_length=3,max_length=32)
    @model_validator(mode='after')
    def valid(self):
        coords=(self.center_mm or [])+[v for p in self.points_mm or [] for v in p]
        if any(not math.isfinite(v) or abs(v)>2000 for v in coords):raise ValueError('Cut coordinates must be finite and bounded')
        if self.kind=='slot':
            if self.center_mm is None or self.length_mm is None or self.width_mm is None or self.points_mm is not None:raise ValueError('Slot requires center, overall length and width only')
            if self.length_mm<=self.width_mm+1e-4:raise ValueError('Slot overall length must exceed width; use a hole for a circle')
        else:
            if self.points_mm is None or any(v is not None for v in (self.center_mm,self.length_mm,self.width_mm)) or self.angle_deg!=0:raise ValueError('Pocket requires a simple polygon without slot parameters')
            from shapely.geometry import Polygon
            polygon=Polygon(self.points_mm)
            if not polygon.is_valid or polygon.area<1e-4 or any(math.dist(p,q)<1e-4 for p,q in zip(self.points_mm,self.points_mm[1:]+self.points_mm[:1])):raise ValueError('Pocket polygon is degenerate, self-intersecting or has repeated adjacent vertices')
        return self
    def area_mm2(self):
        if self.kind=='slot':return self.width_mm*(self.length_mm-self.width_mm)+math.pi*(self.width_mm/2)**2
        return abs(sum(p[0]*q[1]-q[0]*p[1] for p,q in zip(self.points_mm,self.points_mm[1:]+self.points_mm[:1])))/2
    def slot_centers(self):
        a=math.radians(self.angle_deg);u=[math.cos(a),math.sin(a)];h=(self.length_mm-self.width_mm)/2
        return [[self.center_mm[i]-h*u[i] for i in range(2)],[self.center_mm[i]+h*u[i] for i in range(2)]]
    @property
    def point_mm(self):
        if self.kind=='slot':return [*self.center_mm,self.z_mm]
        from shapely.geometry import Polygon
        p=Polygon(self.points_mm).representative_point();return [p.x,p.y,self.z_mm]
    @property
    def outward(self):return '+z'

def expected_edges(op,bottom):
    lines=[];arcs=[]
    def line(a,b,z):return {'a':[*a,z],'b':[*b,z]}
    if op.kind=='pocket':
        for z in (op.z_mm,bottom):lines += [line(p,q,z) for p,q in zip(op.points_mm,op.points_mm[1:]+op.points_mm[:1])]
        lines += [{'a':[*p,bottom],'b':[*p,op.z_mm]} for p in op.points_mm]
    else:
        c1,c2=op.slot_centers();a=math.radians(op.angle_deg);u=[math.cos(a),math.sin(a)];n=[-u[1],u[0]];r=op.width_mm/2
        endpoints=[[c[i]+sign*r*n[i] for i in range(2)] for c in (c1,c2) for sign in (-1,1)]
        for z in (op.z_mm,bottom):
            lines += [line(endpoints[0],endpoints[2],z),line(endpoints[1],endpoints[3],z)]
            for center,sign,ends in ((c1,-1,endpoints[:2]),(c2,1,endpoints[2:])):
                arcs.append({'center':[*center,z],'radius_mm':r,'ends':[[*p,z] for p in ends],'mid':[*[center[i]+sign*r*u[i] for i in range(2)],z]})
    return {'lines':lines,'arcs':arcs}

def edge_snapshot(doc):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    lines=[];arcs=[]
    for body in get(doc,'GetBodies2',0,False) or []:
        for edge in get(body,'GetEdges') or []:
            curve=get(edge,'GetCurve');params=list(get(edge,'GetCurveParams2'));a=[v*1000 for v in params[:3]];b=[v*1000 for v in params[3:6]]
            if get(curve,'IsLine'):lines.append({'a':a,'b':b})
            elif get(curve,'IsCircle'):
                c=list(get(curve,'CircleParams'));mid=list(typed(edge,'IEdge').Evaluate2((params[6]+params[7])/2,0))
                if len(mid)!=4 or struct.unpack('<ii',struct.pack('<d',mid[-1]))[0]!=1:raise RuntimeError('Native cut arc evaluation failed')
                arcs.append({'center':[v*1000 for v in c[:3]],'radius_mm':c[6]*1000,'ends':[a,b],'mid':[v*1000 for v in mid[:3]]})
    return {'lines':lines,'arcs':arcs}

def geometry(doc,record,actual=None):
    actual=edge_snapshot(doc) if actual is None else actual;wanted=record['expected_edges']
    def point(a,b):return math.dist(a,b)<1e-4
    def segment(a,b):return (point(a['a'],b['a']) and point(a['b'],b['b'])) or (point(a['a'],b['b']) and point(a['b'],b['a']))
    lines=all(any(segment(w,a) for a in actual['lines']) for w in wanted['lines'])
    arcs=all(any(point(w['center'],a['center']) and abs(w['radius_mm']-a['radius_mm'])<1e-4 and point(w['mid'],a['mid']) and
        ((point(w['ends'][0],a['ends'][0]) and point(w['ends'][1],a['ends'][1])) or (point(w['ends'][0],a['ends'][1]) and point(w['ends'][1],a['ends'][0]))) for a in actual['arcs']) for w in wanted['arcs'])
    return {'passed':bool(lines and arcs),'straight_edges_verified':lines,'native_arc_edges_verified':arcs,'expected_straight_edges':len(wanted['lines']),'expected_arc_edges':len(wanted['arcs']),'top_z_mm':record['operation']['z_mm'],'bottom_z_mm':record['bottom_z_mm'],'source':'native exact straight/circular B-Rep edges, including both depths'}

def read(doc,record,actual=None):
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_sketch_quality import inspect_sketch
    from solidworks_mcp.automation.com_utils import typed
    from .feature_types import feature_type
    op=PlanarCut.model_validate(record['operation']);feature=doc.FeatureByName(record['feature']);sketch_feature=doc.FeatureByName(record['sketch'])
    if feature is None or sketch_feature is None:raise RuntimeError('Native cut or driving sketch disappeared')
    data=typed(get(feature,'GetDefinition'),'IExtrudeFeatureData2');condition=int(data.GetEndCondition(True));depth=float(data.GetDepth(True))*1000
    quality=inspect_sketch(get(sketch_feature,'GetSpecificFeature2'));parents=[str(get(f,'Name')) for f in get(feature,'GetParents') or []]
    measured=geometry(doc,record,actual)
    kind,raw=feature_type(feature)
    passed=kind=='Cut' and condition==(1 if op.depth_mm is None else 0) and (op.depth_mm is None or math.isclose(depth,op.depth_mm,abs_tol=1e-5)) and quality['status']=='pass' and record['sketch'] in parents and measured['passed']
    result={'feature':record['feature'],'type':kind,'raw_type':raw,'end_condition':condition,'depth_mm':None if condition==1 else depth,'sketch':quality,'consumed_sketch_verified':record['sketch'] in parents,'geometry':measured,'passed':bool(passed)}
    if not passed:
        import json
        raise RuntimeError('Native cut parameters, geometry or constraints failed: '+json.dumps(result,ensure_ascii=True))
    return result

def apply(app,doc,operations):
    from scripts.sw_connect import get_com_member as get,create_empty_dispatch_variant
    from scripts.sw_part import end_sketch,sketch_line,extrude_cut
    from scripts.sw_sketch_quality import fully_define_sketch
    from integrations.czuryk.native_only import native_automation
    from solidworks_mcp.automation.com_utils import typed,transform_point
    from engineering.standard_holes import entry
    from engineering.native import _exact_bounds
    def volume():return sum(float(list(get(b,'GetMassProperties',1000.))[3])*1e9 for b in get(doc,'GetBodies2',0,False) or [])
    adapter=native_automation(app);results=[]
    for index,op in enumerate(operations):
        bodies=list(get(doc,'GetBodies2',0,False) or []);bound=_exact_bounds(bodies)
        if len(bodies)!=1 or abs(bound['max'][2]-op.z_mm)>1e-4:raise ValueError('Planar cuts require the exact highest local +Z face of one solid')
        bottom=bound['min'][2] if op.depth_mm is None else op.z_mm-op.depth_mm
        if bottom<bound['min'][2]-1e-4 or (op.depth_mm is not None and bottom<=bound['min'][2]+1e-4):raise ValueError('Blind depth reaches/exceeds stock; use explicit Through All')
        initial=volume();expected_removed=op.area_mm2()*(op.z_mm-bottom)
        if expected_removed>=initial:raise ValueError('Cut cannot remove the entire part')
        entry(doc,op);manager=typed(doc.SketchManager,'ISketchManager');manager.InsertSketch(True);active=get(manager,'ActiveSketch');sketch_name=None
        try:
            transform=get(get(active,'ModelToSketchTransform'),'ArrayData')
            def local(p):return transform_point(transform,[p[0]/1000,p[1]/1000,op.z_mm/1000])
            if op.kind=='slot':
                c1,c2=op.slot_centers();a=math.radians(op.angle_deg);side=[op.center_mm[0]-math.sin(a)*op.width_mm/2,op.center_mm[1]+math.cos(a)*op.width_mm/2]
                p1,p2,p3=map(local,(c1,c2,side))
                made=manager.CreateSketchSlot(0,0,op.width_mm/1000,*p1,*p2,*p3,1,False)
                if not made:raise RuntimeError('Native straight slot sketch creation failed')
            else:
                points=[local(p) for p in op.points_mm];segments=[];old=get(manager,'AddToDB')
                try:
                    manager.AddToDB=True
                    for p,q in zip(points,points[1:]+points[:1]):
                        segment=sketch_line(doc,p[0],p[1],q[0],q[1])
                        if segment is None:raise RuntimeError('Native polygon segment failed')
                        segments.append(segment)
                finally:manager.AddToDB=old
                for i,segment in enumerate(segments):
                    doc.ClearSelection2(True)
                    for p in (get(segment,'GetEndPoint2'),get(segments[(i+1)%len(segments)],'GetStartPoint2')):
                        if not p.Select4(True,create_empty_dispatch_variant()):raise RuntimeError('Native polygon endpoint selection failed')
                    get(doc,'SketchAddConstraints','sgCOINCIDENT')
                    p,q=points[i],points[(i+1)%len(points)]
                    relation='sgVERTICAL' if abs(p[0]-q[0])<1e-10 else ('sgHORIZONTAL' if abs(p[1]-q[1])<1e-10 else None)
                    if relation:
                        doc.ClearSelection2(True)
                        if not segment.Select4(False,create_empty_dispatch_variant()):raise RuntimeError('Native polygon line selection failed')
                        get(doc,'SketchAddConstraints',relation)
            with adapter.dimension_input_guard():fully_define_sketch(doc)
        finally:reference=end_sketch(doc)
        feature=extrude_cut(doc,reference,(op.depth_mm or 0)/1000,direction=False)
        if feature is None:raise RuntimeError('Native planar cut failed; no alternate direction was replayed')
        feature.Name='AI_PlanarCut_'+str(index+1)
        sketches=[];sub=get(feature,'GetFirstSubFeature',default=None)
        for _ in range(64):
            if sub is None:break
            if get(sub,'GetTypeName2')=='ProfileFeature':sketches.append(sub)
            sub=get(sub,'GetNextSubFeature',default=None)
        if len(sketches)!=1:raise RuntimeError('Cut must consume exactly one native profile sketch')
        sketches[0].Name='AI_PlanarProfile_'+str(index+1);sketch_name=str(get(sketches[0],'Name'))
        if not get(doc,'ForceRebuild3',False):raise RuntimeError('Planar cut rebuild failed')
        actual=volume()
        if len(list(get(doc,'GetBodies2',0,False) or []))!=1 or not math.isclose(initial-actual,expected_removed,rel_tol=1e-7,abs_tol=.001):raise RuntimeError('Cut overlaps an existing void, escapes stock or removed incorrect depth/area; working copy preserved')
        record={'operation':op.model_dump(),'feature':str(get(feature,'Name')),'sketch':sketch_name,'bottom_z_mm':bottom,'expected_edges':expected_edges(op,bottom),'removed_volume_mm3':initial-actual,'expected_removed_volume_mm3':expected_removed}
        record['native']=read(doc,record);results.append(record)
    return results
