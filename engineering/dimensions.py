"""Bounded native dimension edits on a task-owned copy, with readback."""
from __future__ import annotations
import math
from pydantic import BaseModel,ConfigDict,Field,model_validator
from typing import Literal


class DimensionChange(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    name:str=Field(pattern=r'^[^@\r\n/\\]{1,100}@[^@\r\n/\\]{1,100}$')
    before_value:float
    value:float=Field(gt=0,le=5000)
    unit:Literal['mm','deg']='mm'

    @model_validator(mode='after')
    def changed(self):
        if math.isclose(self.before_value,self.value,abs_tol=1e-8):raise ValueError('Dimension edit must change its value')
        if self.unit=='deg' and self.value>=360:raise ValueError('Angle must be less than 360 degrees')
        return self


def catalog(doc):
    from scripts.sw_connect import get_com_member as get
    dimensions={};features={}
    def visit(feature,depth=0,managed=False):
        if depth>16:raise RuntimeError('Feature nesting exceeds inspection limit')
        name=str(get(feature,'Name'));kind=str(get(feature,'GetTypeName2'))
        managed_types={'HoleWzd','SweepThread','LPattern','CirPattern','MirrorPattern'}
        managed=managed or kind in managed_types
        owner=get(feature,'GetOwnerFeature',default=None)
        consumers=[owner] if owner is not None else list(get(feature,'GetChildren',default=[]) or [])
        managed=managed or any(str(get(f,'GetTypeName2')) in managed_types for f in consumers)
        if name in features:return
        features[name]=kind
        display=get(feature,'GetFirstDisplayDimension',default=None)
        for _ in range(512):
            if display is None:break
            dimension=get(display,'GetDimension2',0)
            if dimension is not None:
                full=str(get(dimension,'FullName'));key='@'.join(full.split('@')[:2])
                dtype=int(get(display,'Type2'));angular=dtype in {3,16}
                raw=float(get(dimension,'SystemValue'))
                state=int(get(dimension,'DrivenState'))
                dimensions[key]={'name':key,'feature':key.split('@')[1],'feature_type':features.get(key.split('@')[1],kind),'dimension_type':dtype,
                    'value':math.degrees(raw) if angular else raw*1000,'unit':'deg' if angular else 'mm',
                    'driven_state':state,'editable':not managed and state==2 and dtype in {2,3,4,5,6,11,12,14,15,16},'native_standard_managed':managed}
            display=get(feature,'GetNextDisplayDimension',display,default=None)
        else:raise RuntimeError('Dimension catalog exceeds inspection limit')
        child=get(feature,'GetFirstSubFeature',default=None)
        for _ in range(512):
            if child is None:break
            visit(child,depth+1,managed);child=get(child,'GetNextSubFeature',default=None)
    feature=get(doc,'FirstFeature',default=None)
    for _ in range(2048):
        if feature is None:break
        visit(feature);feature=get(feature,'GetNextFeature',default=None)
    return {'dimensions':list(dimensions.values()),'features':features}


def verify(doc,evidence):
    actual=catalog(doc);baseline=evidence.get('after_operations',evidence['before']);before={d['name']:d for d in baseline['dimensions']}
    before.update({d['name']:d for d in evidence['before']['dimensions']})
    current={d['name']:d for d in actual['dimensions']};changes={c['name']:c for c in evidence['changes']}
    failures=[]
    if actual['features']!=baseline['features']:failures.append('Feature tree changed unexpectedly')
    if any(actual['features'].get(k)!=v for k,v in evidence['before']['features'].items()):failures.append('Original feature identities changed')
    if set(before)!=set(current):failures.append('Dimension catalog changed')
    for name,old in before.items():
        now=current.get(name);wanted=changes[name]['value'] if name in changes else old['value']
        if now is None or now['unit']!=old['unit'] or not math.isclose(now['value'],wanted,rel_tol=1e-8,abs_tol=1e-5):
            failures.append('Dimension readback differs: '+name)
    return {'passed':not failures,'issues':failures,'actual':actual,'unrequested_dimensions_preserved':not failures}


def apply(doc,changes):
    from scripts.sw_connect import get_com_member as get
    before=catalog(doc);by_name={d['name']:d for d in before['dimensions']}
    for change in changes:
        old=by_name.get(change.name)
        if not old or not old['editable'] or old['unit']!=change.unit:raise ValueError('Dimension is absent, driven, or has incompatible units: '+change.name)
        if not math.isclose(old['value'],change.before_value,abs_tol=1e-5,rel_tol=1e-8):raise ValueError('Stale dimension value: '+change.name)
    evidence={'before':before,'changes':[c.model_dump() for c in changes]}
    for change in changes:
        dimension=doc.Parameter(change.name)
        raw=math.radians(change.value) if change.unit=='deg' else change.value/1000
        if int(dimension.SetSystemValue3(raw,1,None))!=0:raise RuntimeError('Native dimension update rejected: '+change.name)
    if not get(doc,'ForceRebuild3',False):raise RuntimeError('Dimension edit did not rebuild')
    evidence['after']=verify(doc,evidence)
    if not evidence['after']['passed']:raise RuntimeError('; '.join(evidence['after']['issues']))
    return evidence
