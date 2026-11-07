"""Bounded editable single-part manufacturing drawings; model bytes stay local."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    axis: Literal['x', 'y'] = 'x'
    at_mm: float | None = Field(default=None, ge=-2000, le=2000)
    label: Literal['A'] = 'A'


class ManufacturingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    title: str = Field(default='零件工程图', min_length=1, max_length=80, pattern=r'^[^\x00-\x1f]+$')
    paper: Literal['A3'] = 'A3'
    projection: Literal['first_angle'] = 'first_angle'
    side_view: Literal['left'] = 'left'
    scale: float | None = Field(default=None, ge=.05, le=5)
    dimensions: bool = True
    hole_positions: bool = True
    hole_callouts: bool = True
    section: SectionRequest | None = Field(default_factory=SectionRequest)


STAGES = ('创建原生工程图和第一角三视图', '添加实际尺寸和孔标注', '创建真实剖视图', '保存重开、PDF导出和交付复核')
