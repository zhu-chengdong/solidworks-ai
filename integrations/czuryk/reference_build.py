"""Bounded reference geometry; model output is data, never executable Python."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .loft_spec import AircraftParameters, LoftComponent, resolved_components


class CircularHole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float = Field(ge=-2000, le=2000)
    y_mm: float = Field(ge=-2000, le=2000)
    radius_mm: float = Field(gt=0, le=500)


class ReferenceGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: Literal["prism", "revolve", "loft_scene", "cartoon_aircraft"]
    points: list[list[float]] = Field(default_factory=list, max_length=32)
    depth_mm: float = Field(gt=0, le=2000)
    holes: list[CircularHole] = Field(default_factory=list, max_length=12)
    components: list[LoftComponent] = Field(default_factory=list,max_length=24)
    aircraft: AircraftParameters | None = None

    @model_validator(mode="after")
    def check_geometry(self):
        if self.family in {'loft_scene','cartoon_aircraft'}:
            if self.points or self.holes:raise ValueError('Loft scenes cannot also contain prism/revolve profiles')
            if self.family=='cartoon_aircraft' and (self.aircraft is None or self.components):
                raise ValueError('Aircraft requires high-level aircraft parameters, not raw components')
            if self.family=='loft_scene' and (not self.components or self.aircraft is not None):
                raise ValueError('Loft scene requires explicit components')
            components=resolved_components(self)
            if len({c.name for c in components})!=len(components) or sum(len(c.sections) for c in components)>100:
                raise ValueError('Duplicate component names or excessive native sketch count')
            return self
        if len(self.points)<2 or self.components or self.aircraft is not None:
            raise ValueError('Invalid native profile specification')
        if any(len(p) != 2 or any(not math.isfinite(v) or abs(v) > 2000 for v in p) for p in self.points):
            raise ValueError("Profile requires finite pairs within 2000 mm")
        if not math.isfinite(self.depth_mm):
            raise ValueError("Depth must be finite")
        if self.family == "prism":
            from shapely.geometry import Polygon
            if len(self.points) < 3 or not Polygon(self.points).is_valid or Polygon(self.points).area <= 1e-6:
                raise ValueError("Prism requires a simple closed profile with positive area")
            from shapely.geometry import Point
            polygon = Polygon(self.points)
            for i, hole in enumerate(self.holes):
                center = Point(hole.x_mm, hole.y_mm)
                if not polygon.contains(center) or center.distance(polygon.boundary) <= hole.radius_mm + 1e-5:
                    raise ValueError("Each circular through hole must be strictly inside the profile")
                if any(math.hypot(hole.x_mm-other.x_mm, hole.y_mm-other.y_mm)
                       <= hole.radius_mm+other.radius_mm+1e-5 for other in self.holes[:i]):
                    raise ValueError("Circular holes must not intersect or touch")
        elif (any(p[1] <= 0 for p in self.points)
              or any(b[0] <= a[0] for a, b in zip(self.points, self.points[1:]))):
            raise ValueError("Revolve requires increasing axial coordinates and positive radii")
        if self.family == 'revolve' and self.holes:
            raise ValueError("Circular through holes are supported only for prism profiles")
        return self

    def expected_volume(self):
        if self.family in {'loft_scene','cartoon_aircraft'}:return None
        if self.family == "prism":
            from shapely.geometry import Polygon
            return (Polygon(self.points).area - sum(math.pi*h.radius_mm**2 for h in self.holes)) * self.depth_mm
        return sum(math.pi * (b[0]-a[0]) * (a[1]**2+a[1]*b[1]+b[1]**2)/3
                   for a, b in zip(self.points, self.points[1:]))

    def program(self):
        if self.family not in {'prism','revolve'}:
            raise ValueError('Loft scenes use bounded native batches, never legacy code')
        if self.holes:
            raise ValueError('Hole profiles use the dimensioned native adapter, not the legacy program')
        lines, points, parameters = [], [], {}
        for pair in self.points:
            names = []
            for axis, value in enumerate(pair):
                if value == 0:
                    names.append("0")
                    continue
                key = (axis, value)
                if key not in parameters:
                    name = f"P{len(parameters)+1}"
                    parameters[key] = name
                    lines.append(f"{name}=model.parameter('{name}',{value!r})")
                names.append(parameters[key])
            points.append("("+",".join(names)+")")
        profile = "["+",".join(points)+"]"
        if self.family == "prism":
            lines += [f"Depth=model.parameter('Depth',{self.depth_mm!r})",
                      f"model.prism('ReferencePart',{profile},Depth)"]
        else:
            lines.append(f"model.revolve('ReferencePart',{profile})")
        return "\n".join(lines)


def build_reference(app, spec_path: str, output_path: str, output_root: str, component_start: int = 0):
    import sys
    print("Reference build: validate specification", file=sys.stderr, flush=True)
    root = Path(output_root).resolve()
    source, output = Path(spec_path).resolve(), Path(output_path).resolve()
    if (not source.is_relative_to(root) or not output.is_relative_to(root)
            or source.parent != output.parent or source.name != "reference-spec.json"
            or output.suffix.lower() != ".sldprt" or (output.exists() and component_start==0)):
        raise ValueError("Reference input and new output must be in the same allowed task directory")
    if source.stat().st_size > 32000:
        raise ValueError("Reference specification too large")
    spec = ReferenceGeometry.model_validate_json(source.read_text(encoding="utf-8"))
    from .native_only import native_automation
    print("Reference build: load native adapter", file=sys.stderr, flush=True)
    automation = native_automation(app)
    if spec.family in {'loft_scene','cartoon_aircraft'}:
        from .loft_native import build_batch
        return build_batch(automation,spec,source,output,component_start)
    if component_start:raise ValueError('Simple native profiles have only one build stage')
    automation._runtime.progress_sink = lambda event: print("Reference build stage: " + str(event.get('stage')), file=sys.stderr, flush=True)
    print("Reference build: create dimensioned native sketch", file=sys.stderr, flush=True)
    import faulthandler
    faulthandler.dump_traceback_later(45, file=sys.stderr)
    try:
        from .dimensioned import create_dimensioned_part, geometry_evidence
        doc, result = create_dimensioned_part(automation, spec, output)
        measured = geometry_evidence(automation, doc, spec)
    finally:
        faulthandler.cancel_dump_traceback_later()
    from solidworks_mcp.automation.com_utils import com_get
    passed = measured['passed']
    report = {"spec": spec.model_dump(), "native": result, "geometry": measured}
    (output.parent / 'reference-native.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return {"status": "ok" if passed else "review_required", "success": passed,
        "document": {"title": str(com_get(doc, 'GetTitle')), "path": str(output), "type": 1},
        **measured, "sketch_quality": result['sketch_quality'],
        "native_only_audit": automation.native_only_audit, "native_build": result}
