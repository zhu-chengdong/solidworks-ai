"""Native ISO Hole Wizard adapter, adapted from MIT hjbaard/SolidWorks-MCP.

Upstream reference: ddcefc0cfa056002ff8eb8bdb186818ad52dc2f1,
session.py add_hole_wizard/_wizard_values/_pin_wizard_position.
Copyright (c) 2026 Henk Jan Baard. See release_tools/licenses/HJBAARD-MIT.txt.
"""
from __future__ import annotations
import math
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class StandardHole(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    kind:Literal['clearance','counterbore','countersink','tapped']
    size:Literal['M3','M4','M5','M6','M8','M10','M12']
    point_mm:list[float]=Field(min_length=3,max_length=3)
    outward:Literal['+x','-x','+y','-y','+z','-z']='+z'
    depth_mm:float|None=Field(default=None,gt=0,le=500)
    fit:Literal['close','normal','loose']='normal'
    thread_representation:Literal['cosmetic','modeled']='cosmetic'
    thread_depth_mm:float|None=Field(default=None,gt=0,le=200)
    @model_validator(mode='after')
    def finite(self):
        if any(not math.isfinite(v) or abs(v)>2000 for v in self.point_mm):raise ValueError('Invalid hole entry')
        if self.kind=='tapped' and self.fit!='normal':raise ValueError('Tapped holes do not use clearance fits')
        if self.kind!='tapped' and (self.thread_representation!='cosmetic' or self.thread_depth_mm is not None):raise ValueError('Thread options require a tapped hole')
        if self.thread_representation=='modeled' and self.thread_depth_mm is None:raise ValueError('Modeled threads require an explicit thread depth')
        if self.depth_mm is not None and self.thread_depth_mm is not None and self.thread_depth_mm>self.depth_mm:raise ValueError('Thread depth exceeds drill depth')
        if self.thread_representation=='modeled' and self.outward!='+z':raise ValueError('Modeled tapped holes currently require local +Z entry')
        return self

def values(kind,fit,through,thread_depth=None):
    if kind=='tapped':
        result=[-1.]*6+[1.,1. if through else 0.]+[-1.]*4
        return result
    if kind=='clearance':return [float(fit)]+[0. if through else -1.]*11
    return [-1.,-1.,-1.,float(fit)]+[-1.]*8

def entry(doc,op):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    axis='xyz'.index(op.outward[1]);sign=1 if op.outward[0]=='+' else -1
    normal=[0.,0.,0.];normal[axis]=sign;point=[v/1000 for v in op.point_mm];matches=[]
    for body in get(doc,'GetBodies2',0,False) or []:
        for face in get(body,'GetFaces') or []:
            surface=get(face,'GetSurface')
            if not get(surface,'IsPlane'):continue
            plane=list(get(surface,'PlaneParams'))
            if abs(abs(plane[axis])-1)>1e-7:continue
            sense=-1 if get(face,'FaceInSurfaceSense') else 1
            if plane[axis]*sense*sign<1-1e-7:continue
            if abs(sum((p-q)*n for p,q,n in zip(point,plane[3:6],plane[:3])))>1e-7:continue
            closest=get(face,'GetClosestPointOn',*point)
            if closest and math.dist(closest[:3],point)<1e-7:matches.append(face)
    if len(matches)!=1:raise ValueError('Hole entry must lie uniquely inside a planar material face')
    start=[p+n*.001 for p,n in zip(point,normal)];ext=typed(doc.Extension,'IModelDocExtension')
    doc.ClearSelection2(True)
    if not ext.SelectByRay(*start,*[-v for v in normal],.000001,2,False,0,0):raise RuntimeError('Cannot select the native hole entry')
    return point,normal

def pin(app,doc,feature,point):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed,array_r8
    from scripts.sw_sketch_quality import fully_define_sketch,inspect_sketch
    from integrations.czuryk.native_only import native_automation
    candidates=[];sub=get(feature,'GetFirstSubFeature',default=None)
    for _ in range(64):
        if sub is None:break
        if get(sub,'GetTypeName2')=='ProfileFeature':
            sk=get(sub,'GetSpecificFeature2');points=list(get(sk,'GetSketchPoints2') or []);segments=list(get(sk,'GetSketchSegments') or [])
            if len(points)==1 and not segments:candidates.append((sub,sk,points[0]))
        sub=get(sub,'GetNextSubFeature',default=None)
    if len(candidates)!=1:raise RuntimeError('Wizard position sketch is missing or ambiguous')
    position,sketch,point_ref=candidates[0];doc.ClearSelection2(True)
    if not position.Select2(False,0):raise RuntimeError('Cannot select the native position sketch')
    get(doc,'EditSketch')
    try:
        mathutil=typed(get(app,'GetMathUtility'),'IMathUtility');p=typed(mathutil.CreatePoint(array_r8(point)),'IMathPoint');transform=typed(get(sketch,'ModelToSketchTransform'),'IMathTransform')
        local=list(get(typed(p.MultiplyTransform(transform),'IMathPoint'),'ArrayData'))
        if abs(local[2])>1e-7:raise RuntimeError('Hole position is not on its native sketch plane')
        if not typed(point_ref,'ISketchPoint').SetCoords(*local[:3]):raise RuntimeError('Native hole position update failed')
        try:
            with native_automation(app).dimension_input_guard():fully_define_sketch(doc)
        except RuntimeError:
            state=inspect_sketch(sketch)
            if state['constrained_status']!=3 or state['fix_count']!=0 or state['dimension_count']!=0:raise
        evidence=inspect_sketch(sketch)
        if evidence['constrained_status']==3 and evidence['fix_count']==0 and evidence['dimension_count']==0:
            evidence.update(status='pass',native_zero_dof_position=True)
        native=mathutil.CreatePoint(array_r8([get(point_ref,'X'),get(point_ref,'Y'),get(point_ref,'Z')]))
        actual=list(get(typed(typed(native,'IMathPoint').MultiplyTransform(transform.Inverse()),'IMathPoint'),'ArrayData'))
        if math.dist(actual,point)>1e-7:raise RuntimeError('Hole position moved during dimensioning')
        return evidence
    finally:doc.ClearSelection2(True);doc.SketchManager.InsertSketch(True)

def position(feature):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed,transform_point
    from scripts.sw_sketch_quality import inspect_sketch
    matches=[];sub=get(feature,'GetFirstSubFeature',default=None)
    for _ in range(64):
        if sub is None:break
        if get(sub,'GetTypeName2')=='ProfileFeature':
            sk=get(sub,'GetSpecificFeature2');pts=list(get(sk,'GetSketchPoints2') or [])
            if len(pts)==1 and not list(get(sk,'GetSketchSegments') or []):matches.append((sub,sk,pts[0]))
        sub=get(sub,'GetNextSubFeature',default=None)
    if len(matches)!=1:raise RuntimeError('Native standard-hole position is missing or ambiguous')
    feature,sk,p=matches[0];transform=typed(get(sk,'ModelToSketchTransform'),'IMathTransform');inverse=typed(transform.Inverse(),'IMathTransform')
    point=[1000*v for v in transform_point(get(inverse,'ArrayData'),[get(p,'X'),get(p,'Y'),get(p,'Z')])]
    quality=inspect_sketch(sk)
    if quality['constrained_status']==3 and quality['fix_count']==0 and quality['dimension_count']==0:quality.update(status='pass',native_zero_dof_position=True)
    return {'point_mm':point,'sketch_name':str(get(feature,'Name')),'sketch':quality}

def read(doc,name,op,include_thread=True):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    feature=doc.FeatureByName(name)
    if feature is None:raise RuntimeError('Native standard hole disappeared')
    data=typed(get(feature,'GetDefinition'),'IWizardHoleFeatureData2')
    if data is None:raise RuntimeError('Native Hole Wizard definition unavailable')
    info={'feature':name,'type':str(get(feature,'GetTypeName2')),'standard':'ISO','requested_kind':op.kind,'requested_size':op.size,'requested_fit':op.fit}
    for field in ('Diameter','Depth','HoleDiameter','ThruHoleDiameter','HoleDepth','CounterBoreDiameter','CounterBoreDepth','CounterSinkDiameter','TapDrillDiameter','ThruTapDrillDiameter','ThreadDiameter','ThreadDepth','TapDrillDepth','ThruHoleDepth'):
        value=get(data,field,default=None)
        if value is not None:info[field+'_mm']=float(value)*1000
    for field in ('Type','Standard','Standard2','FastenerType','FastenerType2','EndCondition','FastenerSize','HoleFit','CosmeticThreadType','CounterSinkAngle','DrillAngle'):
        value=get(data,field,default=None)
        if value is not None:info[field]=value
    fasteners={'clearance':144,'counterbore':139,'countersink':140,'tapped':147}
    info['passed']=info.get('Standard2')==8 and info.get('FastenerSize')==op.size and info.get('FastenerType2')==fasteners[op.kind] and info.get('EndCondition')==(1 if op.depth_mm is None else 0)
    if op.kind!='tapped':info['passed'] &= info.get('HoleFit')=={'close':0,'normal':1,'loose':2}[op.fit]
    info['position']=position(feature)
    info['passed'] &= math.dist(info['position']['point_mm'],op.point_mm)<1e-4 and info['position']['sketch']['status']=='pass'
    if op.thread_depth_mm is not None:info['passed'] &= math.isclose(info['ThreadDepth_mm'],op.thread_depth_mm,abs_tol=1e-4)
    if not info['passed']:
        import json
        raise RuntimeError('Native Hole Wizard readback differs: '+json.dumps(info,ensure_ascii=False))
    if include_thread and op.thread_representation=='modeled':
        from .threads import MetricThread,read as read_thread
        thread=MetricThread(size=op.size,internal=True,point_mm=op.point_mm,length_mm=op.thread_depth_mm)
        info['thread']=read_thread(doc,name+'_Thread',thread)
    return info

def set_thread_depth(doc,feature,op):
    if op.thread_depth_mm is None:return
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    feature=typed(feature,'IFeature')
    data=typed(get(feature,'GetDefinition'),'IWizardHoleFeatureData2')
    if not data.AccessSelections(doc,None):raise RuntimeError('Cannot access the native tapped-hole definition')
    try:
        data.ThreadEndCondition=0;data.ThreadDepth=op.thread_depth_mm/1000
        if not feature.ModifyDefinition(data,doc,None):raise RuntimeError('Native tapped-hole thread depth modification failed')
    except BaseException:
        data.ReleaseSelectionAccess();raise


def apply(app,doc,operations):
    from scripts.sw_connect import get_com_member as get
    from solidworks_mcp.automation.com_utils import typed
    kinds={'clearance':(2,144),'counterbore':(0,139),'countersink':(1,140),'tapped':(4,147)};results=[]
    def volume():return sum(float(list(get(b,'GetMassProperties',1000.))[3])*1e9 for b in get(doc,'GetBodies2',0,False) or [])
    for i,op in enumerate(operations):
        initial_volume=volume()
        point,normal=entry(doc,op);kind,fastener=kinds[op.kind];through=op.depth_mm is None;diameter=-1.
        if op.thread_representation=='modeled':
            from .threads import MetricThread,definition
            thread=MetricThread(size=op.size,internal=True,point_mm=op.point_mm,length_mm=op.thread_depth_mm)
            definition(app,doc,thread);diameter=thread.carrier_diameter_mm/1000
        try:
            feature=typed(doc.FeatureManager,'IFeatureManager').HoleWizard5(kind,8,fastener,op.size,1 if through else 0,diameter,-1. if through else op.depth_mm/1000,-1.,*values(op.kind,{'close':0,'normal':1,'loose':2}[op.fit],through,op.thread_depth_mm),'',False,False,True,False,False,False)
            if feature is None:raise RuntimeError('Native Hole Wizard rejected this standard size; no simple-hole substitution was used')
            feature.Name='AI_StandardHole_'+str(i+1)
            quality=pin(app,doc,feature,point)
            set_thread_depth(doc,feature,op)
            if not get(doc,'ForceRebuild3',False):raise RuntimeError('Standard hole rebuild failed')
            evidence=read(doc,str(get(feature,'Name')),op,include_thread=False)
            if op.thread_representation=='modeled':
                from .threads import apply as create_thread
                if not math.isclose(evidence.get('TapDrillDiameter_mm') or evidence.get('ThruTapDrillDiameter_mm'),thread.carrier_diameter_mm,abs_tol=1e-4):raise RuntimeError('Native tap drill override differs from the modeled-thread carrier')
                made=create_thread(app,doc,[thread])[0];thread_feature=doc.FeatureByName(made['native']['feature']);thread_feature.Name=str(get(feature,'Name'))+'_Thread'
                evidence=read(doc,str(get(feature,'Name')),op)
            removed=initial_volume-volume()
            if removed<=0:raise RuntimeError('Standard hole removed no material')
            results.append({'operation':op.model_dump(),'native':evidence,'position_sketch':quality,'removed_volume_mm3':removed})
        finally:doc.ClearSelection2(True)
    return results

