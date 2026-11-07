"""A bounded flat-assembly drawing request; native BOM and balloons are required."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

class AssemblyDrawingRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    title:str=Field(default='装配工程图',min_length=1,max_length=80,pattern=r'^[^\x00-\x1f]+$')
    paper:Literal['A3']='A3'
    projection:Literal['first_angle']='first_angle'
    scale:float|None=Field(default=None,ge=.05,le=2)
    bom:Literal[True]=True
    balloons:Literal[True]=True

STAGES=('复制并核对原生装配依赖、创建工程图','插入并核对原生BOM','插入每个组件的关联序号气泡','保存重开、核对关联并导出PDF和依赖包')

def validate_bom(rows,components):
    expected={c['name']:c for c in components};seen=set();items=set()
    for row in rows:
        names=row['components']
        if not row['item'].isdigit() or int(row['item'])<1 or row['item'] in items:raise ValueError('Invalid or duplicate native BOM item')
        items.add(row['item'])
        if row['quantity']!=len(names) or not names or len(set(names))!=len(names):raise ValueError('BOM quantity differs from its actual components')
        if any(n not in expected or n in seen for n in names):raise ValueError('BOM component identity differs from the assembly')
        if len({expected[n]['path'] for n in names})!=1:raise ValueError('One BOM row combines different native documents')
        seen.update(names)
    if seen!=set(expected):raise ValueError('BOM omitted an assembly component')

def validate_balloons(balloons,rows,components):
    validate_bom(rows,components)
    mapping={n:r['item'] for r in rows for n in r['components']}
    if len(balloons)!=len(mapping) or {b['component'] for b in balloons}!=set(mapping):raise ValueError('Every assembly instance needs its own associated balloon')
    for b in balloons:
        if b['item']!=mapping[b['component']] or not b['is_bom_balloon'] or b['upper_text_content']!=1 or b['text_style']!=2 or b['attached_count']!=1:
            raise ValueError('A balloon lost its native BOM number or component attachment')
