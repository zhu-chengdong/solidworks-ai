"""Strict, provider-independent data for smooth native multibody lofts."""
from __future__ import annotations

import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoftSection(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    station_mm: float = Field(ge=-1000, le=1000)
    u_mm: float = Field(ge=-1000, le=1000)
    v_mm: float = Field(ge=-1000, le=1000)
    radius_u_mm: float = Field(ge=.05, le=500)
    radius_v_mm: float = Field(ge=.05, le=500)


class LoftComponent(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,35}$')
    axis: Literal['X','Y','Z']
    sections: list[LoftSection] = Field(min_length=3, max_length=10)
    color_rgb: list[float] = Field(min_length=3, max_length=3)

    @model_validator(mode='after')
    def valid(self):
        if any(not 0 <= c <= 1 or not math.isfinite(c) for c in self.color_rgb):
            raise ValueError('Color channels must be finite in [0,1]')
        if any(b.station_mm-a.station_mm < .05 for a,b in zip(self.sections,self.sections[1:])):
            raise ValueError('Loft stations must be strictly increasing with at least .05 mm spacing')
        return self


class AircraftParameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    length_mm: float = Field(default=160, ge=50, le=400)
    fuselage_width_mm: float = Field(default=48, ge=15, le=120)
    fuselage_height_mm: float = Field(default=50, ge=15, le=120)
    wingspan_mm: float = Field(default=160, ge=70, le=500)
    wing_chord_mm: float = Field(default=50, ge=15, le=100)
    wing_sweep_mm: float = Field(default=28, ge=0, le=70)
    tail_span_mm: float = Field(default=55, ge=20, le=150)
    fin_height_mm: float = Field(default=34, ge=10, le=90)
    window_count: int = Field(default=4, ge=1, le=6)
    body_rgb: list[float] = Field(default_factory=lambda:[.96,.97,1.], min_length=3,max_length=3)
    accent_rgb: list[float] = Field(default_factory=lambda:[.31,.48,.91],min_length=3,max_length=3)
    glass_rgb: list[float] = Field(default_factory=lambda:[.43,.64,.98],min_length=3,max_length=3)

    @model_validator(mode='after')
    def proportions(self):
        if self.wingspan_mm < self.fuselage_width_mm*1.6 or self.fuselage_width_mm > self.length_mm*.65:
            raise ValueError('Inconsistent fuselage/wing proportions')
        for rgb in (self.body_rgb,self.accent_rgb,self.glass_rgb):
            if any(not math.isfinite(v) or not 0<=v<=1 for v in rgb):
                raise ValueError('Color channels must be finite in [0,1]')
        return self


def aircraft_components(p: AircraftParameters):
    """A declared visual-proportion recipe; all lengths remain native dimensions.

    World axes: X nose to tail, Y span, Z up. Hidden windows/wings are mirrored.
    Components deliberately remain separate editable solids for colors.
    """
    L=p.length_mm;W=p.fuselage_width_mm;H=p.fuselage_height_mm
    cy=p.wingspan_mm/2+10;cz=H*.75;wing_z=cz-H*.23
    result=[]
    def add(name,axis,rows,rgb):
        result.append(LoftComponent(name=name,axis=axis,color_rgb=rgb,
            sections=[LoftSection(station_mm=s,u_mm=u,v_mm=v,radius_u_mm=ru,radius_v_mm=rv) for s,u,v,ru,rv in rows]))
    shape=[(.0,.018,.018),(.035,.36,.43),(.14,.82,.89),(.32,1.,1.),(.57,.91,.88),(.78,.64,.62),(.94,.31,.31),(1.,.018,.018)]
    for name,rgb,belly in [('Fuselage',p.body_rgb,False),('BlueBelly',p.accent_rgb,True)]:
        rows=[]
        for t,fw,fh in shape:
            body_z=cz+H*.04*math.sin(math.pi*t)
            rows.append((10+L*t,cy,body_z-(H*.04*fh if belly else 0),
                         max(.1,W*.5*fw*(.94 if belly else 1)),max(.08,H*.5*fh*(.94 if belly else 1))))
        add(name,'X',rows,rgb)
    for side in (-1,1):
        rows=[]
        for t,scale in [(0,1),(.45,.9),(.87,.5),(1,.025)]:
            rows.append((cy+side*p.wingspan_mm*.5*t,10+L*.46+p.wing_sweep_mm*t,wing_z-H*.04*t,
                         max(.2,p.wing_chord_mm*.5*scale),max(.1,H*.055*scale)))
        add('WingLeft' if side<0 else 'WingRight','Y',sorted(rows),p.body_rgb)
        rows=[]
        for t,scale in [(0,1),(.65,.8),(1,.025)]:
            rows.append((cy+side*p.tail_span_mm*.5*t,10+L*.88+L*.035*t,cz+H*.02,
                         max(.2,L*.105*scale),max(.1,H*.032*scale)))
        add('TailLeft' if side<0 else 'TailRight','Y',sorted(rows),p.body_rgb)
    rows=[]
    for t,scale in [(0,1),(.55,.78),(.9,.45),(1,.025)]:
        rows.append((cz+H*.05+p.fin_height_mm*t,10+L*.84+L*.075*t,cy,
                     max(.2,L*.10*scale),max(.1,W*.065*scale)))
    add('TailFin','Z',rows,p.body_rgb)
    # Glass lenses meet the estimated side surface; both sides share proportions.
    def side_surface(t,z):
        a,b=next((a,b) for a,b in zip(shape,shape[1:]) if a[0]<=t<=b[0])
        fraction=(t-a[0])/(b[0]-a[0])
        fw=a[1]+fraction*(b[1]-a[1]);fh=a[2]+fraction*(b[2]-a[2])
        center_z=cz+H*.04*math.sin(math.pi*t)
        return W*.5*fw*math.sqrt(max(.01,1-((z-center_z)/(H*.5*fh))**2))
    for side in (-1,1):
        for i in range(p.window_count):
            t=.35+i*(.40/max(1,p.window_count-1));x=10+L*t
            z=cz+H*.10
            y=cy+side*(side_surface(t,z)+.35)
            rows=[(y-1.6,x,z,L*.026*.12,H*.079*.12),(y,x,z,L*.026,H*.079),(y+1.6,x,z,L*.026*.12,H*.079*.12)]
            add('Window'+('L' if side<0 else 'R')+str(i+1),'Y',rows,p.glass_rgb)
        x=10+L*.125;z=cz+H*.15;y=cy+side*W*.37
        rows=[(y-1,x,z,L*.075*.08,H*.16*.08),(y,x,z,L*.075,H*.16),(y+1,x,z,L*.075*.08,H*.16*.08)]
        add('CockpitLeft' if side<0 else 'CockpitRight','Y',rows,p.glass_rgb)
    return result


def resolved_components(spec):
    if spec.family=='cartoon_aircraft':return aircraft_components(spec.aircraft)
    if spec.family=='loft_scene':return spec.components
    return []
