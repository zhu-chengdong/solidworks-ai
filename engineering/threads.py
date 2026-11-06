"""Real ISO metric Thread adapter with independent native helical-edge checks.

Reference ddcefc0cfa056002ff8eb8bdb186818ad52dc2f1, add_thread.
Copyright (c) 2026 Henk Jan Baard. See release_tools/licenses/HJBAARD-MIT.txt.
"""
from __future__ import annotations
import math,re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
COARSE={'M3':.5,'M4':.7,'M5':.8,'M6':1.,'M8':1.25,'M10':1.5,'M12':1.75}

class MetricThread(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    size:Literal['M3','M4','M5','M6','M8','M10','M12']
    internal:bool=True
    point_mm:list[float]=Field(min_length=3,max_length=3)
    length_mm:float=Field(gt=0,le=200,description='Native Thread blind/helix depth. The complete swept-profile axial range is measured and reported separately.')
    right_handed:bool=True
    @model_validator(mode='after')
    def finite(self):
        if any(not math.isfinite(v) or abs(v)>2000 for v in self.point_mm):raise ValueError('Invalid thread entry')
        if self.length_mm<self.pitch_mm:raise ValueError('Thread length must cover at least one coarse pitch')
        return self
    @property
    def pitch_mm(self):return COARSE[self.size]
    @property
    def nominal_mm(self):return float(self.size[1:])
    @property
    def carrier_diameter_mm(self):return self.nominal_mm-1.08253175473*self.pitch_mm if self.internal else self.nominal_mm

def mouth(doc,op):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    candidates=[]
    for body in get(doc,'GetBodies2',0,False) or []:
        for edge in get(body,'GetEdges') or []:
            curve=typed(get(edge,'GetCurve'),'ICurve')
            if not get(curve,'IsCircle'):continue
            circle=list(get(curve,'CircleParams'));diameter=circle[6]*2000
            if math.dist([v*1000 for v in circle[:3]],op.point_mm)>1e-4:continue
            if abs(diameter-op.carrier_diameter_mm)>1e-4:continue
            parameters=list(get(edge,'GetCurveParams2'))
            if not math.isclose(abs(parameters[7]-parameters[6]),2*math.pi,abs_tol=1e-6):continue
            candidates.append(edge)
    if len(candidates)!=1:raise ValueError(f'Thread needs one full circular entry of diameter {op.carrier_diameter_mm:.6f} mm at the requested point; no approximate profile substitution')
    edge=candidates[0];barrels=[]
    for face in get(edge,'GetTwoAdjacentFaces2') or []:
        surface=typed(get(face,'GetSurface'),'ISurface')
        if not get(surface,'IsCylinder'):continue
        cp=list(get(surface,'CylinderParams'));axis=cp[3:6];circle=list(get(typed(get(edge,'GetCurve'),'ICurve'),'CircleParams'));start=circle[:3]
        if abs(abs(axis[2])-1)>1e-7:raise ValueError('Real metric threads are currently qualified only for local Z-axis cylinders')
        axis_delta=[p-q for p,q in zip(start,cp[:3])];projection=sum(x*n for x,n in zip(axis_delta,axis));radial=[x-projection*n for x,n in zip(axis_delta,axis)]
        # Circle centre is on the axis; evaluate an actual edge point for normal sense.
        params=list(get(edge,'GetCurveParams2'));sample=params[:3]
        delta=[p-q for p,q in zip(sample,cp[:3])];projection=sum(x*n for x,n in zip(delta,axis));radial=[x-projection*n for x,n in zip(delta,axis)]
        normal=list(get(surface,'EvaluateAtPoint',*sample))[:3];sense=-1 if get(face,'FaceInSurfaceSense') else 1
        internal=sum(a*b for a,b in zip(normal,radial))*sense<0
        if internal!=op.internal:raise ValueError('Requested internal/external thread does not match the native cylindrical face')
        ends=[]
        for boundary in get(face,'GetEdges') or []:
            curve=typed(get(boundary,'GetCurve'),'ICurve')
            if not get(curve,'IsCircle'):continue
            data=list(get(curve,'CircleParams'))
            if abs(data[6]*2000-op.carrier_diameter_mm)>1e-4:continue
            if data[2]*1000>op.point_mm[2]+1e-5:raise ValueError('Select the local +Z end of the thread carrier')
            distance=sum((x-y)*n for x,y,n in zip(data[:3],start,axis))*1000;ends.append(distance)
        available=max([abs(t) for t in ends] or [0.])
        if available+1e-5<op.length_mm:raise ValueError('Thread length exceeds its actual cylindrical material span')
        barrels.append({'internal':internal,'available_length_mm':available,'diameter_mm':cp[6]*2000,'axis':axis})
    if len(barrels)!=1:raise ValueError('Thread carrier cylinder is missing or ambiguous')
    return edge,barrels[0]

def definition(app,doc,op):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    fm=typed(doc.FeatureManager,'IFeatureManager');data=typed(fm.CreateDefinition(87),'IThreadFeatureData')
    if data is None:raise RuntimeError('Native Thread feature definition unavailable')
    data.InitializeThreadData();data.Type='Metric Tap' if op.internal else 'Metric Die'
    library=str(get(data,'Type') or '')
    if not library:raise ValueError('Native metric thread profile library is not configured')
    names=list(get(app,'GetConfigurationNames',library) or [])
    choices=[]
    for name in names:
        match=re.fullmatch(r'M([0-9.]+)x([0-9.]+)',name.replace(' ',''),re.I)
        if match and math.isclose(float(match[1]),op.nominal_mm,abs_tol=1e-8) and math.isclose(float(match[2]),op.pitch_mm,abs_tol=1e-8):choices.append(name)
    if len(choices)!=1:raise ValueError('Requested coarse thread size is absent or ambiguous in the installed native library')
    data.Size=choices[0]
    return fm,data,{'library':library,'native_size':choices[0]}

def measure_geometry(faces,op):
    """Measure real thread edges, including feature-less imported STEP bodies."""
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    import struct
    radii=[];helices=[];seen=set();depths=[];evaluated=0
    for face in faces:
        for edge in get(face,'GetEdges') or []:
            native=typed(edge,'IEdge');params=list(get(edge,'GetCurveParams2'));lo,hi=params[6:8]
            endpoints=[params[:3],params[3:6]]
            if min(math.hypot(p[0]*1000-op.point_mm[0],p[1]*1000-op.point_mm[1]) for p in endpoints)>op.nominal_mm/2+.05:continue
            if min(p[2]*1000 for p in endpoints)>op.point_mm[2]+op.pitch_mm or max(p[2]*1000 for p in endpoints)<op.point_mm[2]-op.length_mm-op.pitch_mm:continue
            points=[tuple(v*1000 for v in p) for p in endpoints]
            edge_radii=[math.hypot(p[0]-op.point_mm[0],p[1]-op.point_mm[1]) for p in points]
            if max(edge_radii)<=op.nominal_mm/2+.05:radii.extend(edge_radii)
            if abs(points[0][2]-points[1][2])<=min(op.length_mm,op.pitch_mm)*.5 or abs(edge_radii[0]-edge_radii[1])>.005:continue
            curve=typed(get(edge,'GetCurve'),'ICurve')
            if get(curve,'IsLine') or get(curve,'IsCircle'):continue
            def evaluate(fraction):
                nonlocal evaluated
                values=list(native.Evaluate2(lo+(hi-lo)*fraction,0));evaluated+=1
                if len(values)!=4 or struct.unpack('<ii',struct.pack('<d',values[-1]))[0]!=1 or not all(math.isfinite(v) for v in values[:-1]):raise RuntimeError('Native thread edge evaluation failed')
                return tuple(v*1000 for v in values[:3])
            probe=evaluate(.37)
            key=tuple(round(v,7) for p in endpoints for v in p)+tuple(round(v,5) for v in probe)
            if key in seen:continue
            seen.add(key)
            # Position-based unwrapping also works for STEP spline helices whose
            # native derivative magnitude is not a reliable instantaneous pitch.
            count=max(33,math.ceil((op.length_mm/op.pitch_mm+1)*8)+1)
            samples=[evaluate(i/(count-1)) for i in range(count)]
            edge_radii=[math.hypot(p[0]-op.point_mm[0],p[1]-op.point_mm[1]) for p in samples]
            if max(edge_radii)>op.nominal_mm/2+.05 or max(edge_radii)-min(edge_radii)>.005:continue
            angles=[math.atan2(p[1]-op.point_mm[1],p[0]-op.point_mm[0]) for p in samples]
            increments=[(b-a+math.pi)%(2*math.pi)-math.pi for a,b in zip(angles,angles[1:])]
            if any(abs(v)>math.pi*.9 for v in increments):raise RuntimeError('Thread edge angular sampling cannot safely unwrap the native helix')
            angle=sum(increments)
            if abs(angle)<=.1:continue
            helices.append(2*math.pi*(samples[-1][2]-samples[0][2])/angle);radii.extend(edge_radii)
            depths.extend(op.point_mm[2]-p[2] for p in samples)
    pitch_ok=bool(helices) and all(math.isclose(abs(p),op.pitch_mm,abs_tol=.005,rel_tol=.001) for p in helices)
    handed_ok=bool(helices) and all((p>0)==op.right_handed for p in helices)
    radius_ok=bool(radii) and math.isclose(max(radii),op.nominal_mm/2,abs_tol=.02)
    return {'native_geometry_present':bool(radii and helices),'native_face_count':len(faces),
        'sampled_radial_range_mm':[min(radii),max(radii)] if radii else None,'nominal_radius_verified':radius_ok,
        'native_helix_signed_pitches_mm':helices,'actual_pitch_verified':pitch_ok,'actual_handedness_verified':handed_ok,
        'pitch_mm':sum(abs(p) for p in helices)/len(helices) if helices else None,'pitch_source':'native helical B-Rep edges',
        'axial_depth_range_mm':[min(depths),max(depths)] if depths else None,'evaluated_points':evaluated,
        'measurement_method':'native helical-edge positions with bounded angular unwrapping',
        'passed':bool(pitch_ok and handed_ok and radius_ok)}


def read(doc,name,op):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    feature=doc.FeatureByName(name)
    if feature is None:raise RuntimeError('Real Thread feature disappeared')
    data=typed(get(feature,'GetDefinition'),'IThreadFeatureData')
    evidence={'feature':name,'type':str(get(feature,'GetTypeName2')),'representation':'modeled','size':str(get(data,'Size')),'profile':str(get(data,'Type')),
        'pitch_mm':float(get(data,'Pitch'))*1000,'length_mm':float(get(data,'BlindDepth'))*1000,'right_handed':bool(get(data,'RightHanded')),
        'method':int(get(data,'ThreadMethod')),'end_condition':int(get(data,'EndCondition'))}
    definition_pitch=evidence['pitch_mm'];geometry=measure_geometry(list(get(feature,'GetFaces') or []),op);evidence.update(geometry)
    evidence['pitch_override']=bool(get(data,'PitchOverride'))
    evidence['override_pitch_mm']=definition_pitch if evidence['pitch_override'] else None
    evidence['inactive_override_pitch_mm']=None if evidence['pitch_override'] else definition_pitch
    override_ok=not evidence['pitch_override'] or math.isclose(evidence['override_pitch_mm'],op.pitch_mm,abs_tol=1e-5)
    evidence['passed']=override_ok and evidence['nominal_radius_verified'] and evidence['native_geometry_present'] and evidence['actual_pitch_verified'] and evidence['actual_handedness_verified'] and math.isclose(evidence['length_mm'],op.length_mm,abs_tol=1e-5) and evidence['right_handed']==op.right_handed and evidence['method']==0 and evidence['end_condition']==0 and evidence['type']=='SweepThread'
    if not evidence['passed']:
        import json
        raise RuntimeError('Saved native thread definition differs from the request: '+json.dumps(evidence,ensure_ascii=False))
    return evidence

def apply(app,doc,operations):
    from scripts.sw_connect import get_com_member as get
    results=[]
    for i,op in enumerate(operations):
        edge,carrier=mouth(doc,op);fm,data,library=definition(app,doc,op)
        doc.ClearSelection2(True)
        try:
            if not edge.Select2(False,1):raise RuntimeError('Cannot select the native thread entry')
            data.Edge=edge;data.ThreadMethod=0;data.EndCondition=0;data.BlindDepth=op.length_mm/1000;data.RightHanded=op.right_handed;data.DiameterOverride=False;data.PitchOverride=False
            feature=fm.CreateFeature(data)
            if feature is None:raise RuntimeError('Native real Thread failed; no cosmetic or helix fallback was used')
            feature.Name='AI_MetricThread_'+str(i+1)
            if not get(doc,'ForceRebuild3',False):raise RuntimeError('Native real thread did not rebuild')
            evidence=read(doc,str(get(feature,'Name')),op);results.append({'operation':op.model_dump(),'native':evidence,'library':library,'carrier':carrier})
        finally:doc.ClearSelection2(True)
    return results
