"""Provider-independent part recipes, instances and real assembly mates.

No generated code, COM expressions, file paths or arbitrary tool calls are
accepted in a design. All dimensions use mm; local part XY is the Front plane.
"""
from __future__ import annotations
import math
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from integrations.czuryk.reference_build import ReferenceGeometry,CircularHole
from .dimensions import DimensionChange
from .finishing import EdgeTreatment
from .standard_holes import StandardHole
from .threads import MetricThread
from .patterns import HolePattern,validate_patterns
from .pockets import PlanarCut


def _plane_normal(instance,plane):
    x,y,z=map(math.radians,instance.rotation_deg)
    cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    rotation=[[cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx],
        [sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx],[-sy,cy*sx,cy*cx]]
    axis={'YZ':0,'XZ':1,'XY':2}[plane]
    return [row[axis] for row in rotation]


class PartSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,29}$')
    label:str=Field(default='',max_length=100)
    shape:Literal['plate','l_bracket','shaft','enclosure','profile','existing']
    length_mm:float|None=Field(default=None,gt=0,le=2000)
    width_mm:float|None=Field(default=None,gt=0,le=2000)
    height_mm:float|None=Field(default=None,gt=0,le=2000)
    thickness_mm:float|None=Field(default=None,gt=0,le=500)
    diameter_mm:float|None=Field(default=None,gt=0,le=1000)
    wall_mm:float|None=Field(default=None,gt=0,le=100)
    holes:list[CircularHole]=Field(default_factory=list,max_length=12)
    profile:ReferenceGeometry|None=None
    source_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
    dimension_changes:list[DimensionChange]=Field(default_factory=list,max_length=24)
    edge_treatments:list[EdgeTreatment]=Field(default_factory=list,max_length=8)
    standard_holes:list[StandardHole]=Field(default_factory=list,max_length=12)
    metric_threads:list[MetricThread]=Field(default_factory=list,max_length=8)
    hole_patterns:list[HolePattern]=Field(default_factory=list,max_length=8)
    planar_cuts:list[PlanarCut]=Field(default_factory=list,max_length=12)
    color_rgb:list[Annotated[float,Field(ge=0,le=1)]]=Field(default_factory=lambda:[.72,.77,.83],min_length=3,max_length=3,description='Normalized RGB channels, each from 0 to 1; do not use 0 to 255 values.')

    @model_validator(mode='after')
    def validate_recipe(self):
        needed={'plate':['length_mm','width_mm','thickness_mm'],
            'l_bracket':['length_mm','width_mm','height_mm','thickness_mm'],
            'shaft':['length_mm','diameter_mm'],'enclosure':['length_mm','width_mm','height_mm','wall_mm'],
            'profile':['profile'],'existing':['source_id']}[self.shape]
        missing=[k for k in needed if getattr(self,k) is None]
        if missing:raise ValueError('Missing engineering dimensions: '+', '.join(missing))
        if any(not math.isfinite(c) or not 0<=c<=1 for c in self.color_rgb):raise ValueError('Invalid RGB')
        if self.shape!='existing' and self.source_id:raise ValueError('Only existing parts can reference a CAD input')
        if self.dimension_changes and self.shape!='existing':raise ValueError('Local dimension edits require an uploaded existing part')
        if len({c.name for c in self.dimension_changes})!=len(self.dimension_changes):raise ValueError('Duplicate dimension edit')
        points=[h.point_mm for h in self.standard_holes]
        validate_patterns(self.standard_holes,self.hole_patterns)
        if any(math.dist(p,q)<1e-4 for i,p in enumerate(points) for q in points[i+1:]):raise ValueError('Use a single compound standard-hole operation at each entry')
        if any(math.dist(t.point_mm,h.point_mm)<1e-4 for t in self.metric_threads for h in self.standard_holes):raise ValueError('Use the standard hole modeled option instead of a duplicate thread operation')
        if self.shape=='shaft' and any(not t.internal and abs(t.nominal_mm-self.diameter_mm)>1e-5 for t in self.metric_threads):raise ValueError('External metric thread requires its nominal shaft diameter')
        if self.shape!='profile' and self.profile is not None:raise ValueError('Unexpected free profile')
        if self.shape=='profile' and self.profile.family not in {'prism','revolve'}:raise ValueError('Use the image workflow for smooth loft scenes')
        if self.shape=='l_bracket' and self.thickness_mm>=min(self.length_mm,self.height_mm):raise ValueError('Bracket wall exceeds its legs')
        if self.shape=='enclosure' and 2*self.wall_mm>=min(self.length_mm,self.width_mm,self.height_mm):raise ValueError('Enclosure has no interior cavity')
        if self.shape not in {'plate','l_bracket','profile'} and self.holes:raise ValueError('Holes are supported in extruded profiles')
        if self.shape in {'plate','l_bracket','profile'}:self.geometry()
        return self

    def geometry(self):
        if self.shape=='profile':return self.profile
        if self.shape not in {'plate','l_bracket','enclosure'}:return None
        L=self.length_mm;W=self.width_mm
        if self.shape=='l_bracket':
            H=self.height_mm;t=self.thickness_mm
            points=[[-L/2,-H/2],[L/2,-H/2],[L/2,-H/2+t],[-L/2+t,-H/2+t],[-L/2+t,H/2],[-L/2,H/2]]
            depth=W
        else:
            points=[[-L/2,-W/2],[L/2,-W/2],[L/2,W/2],[-L/2,W/2]]
            depth=self.height_mm if self.shape=='enclosure' else self.thickness_mm
        return ReferenceGeometry(family='prism',points=points,depth_mm=depth,holes=self.holes)

    def expected_volume(self,include_treatments=True):
        if include_treatments and (self.edge_treatments or self.standard_holes or self.metric_threads or self.hole_patterns or self.planar_cuts):return None
        if self.shape=='existing':return None
        if self.shape=='shaft':return math.pi*(self.diameter_mm/2)**2*self.length_mm
        volume=self.geometry().expected_volume()
        if self.shape=='enclosure':volume-=(self.length_mm-2*self.wall_mm)*(self.width_mm-2*self.wall_mm)*(self.height_mm-self.wall_mm)
        return volume


class InstanceSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,29}$')
    part_id:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,29}$')
    position_mm:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
    rotation_deg:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
    fixed:bool=False

    @model_validator(mode='after')
    def finite_pose(self):
        if any(not math.isfinite(v) or abs(v)>5000 for v in self.position_mm+self.rotation_deg):raise ValueError('Invalid assembly pose')
        return self


class MateSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,35}$')
    kind:Literal['coincident','distance','concentric']
    a:str
    b:str
    plane_a:Literal['XY','XZ','YZ']='XY'
    plane_b:Literal['XY','XZ','YZ']='XY'
    distance_mm:float=Field(default=0,ge=0,le=5000)
    flip:bool=False
    radius_a_mm:float|None=Field(default=None,gt=0,le=1000)
    radius_b_mm:float|None=Field(default=None,gt=0,le=1000)
    axis_point_a_mm:list[float]|None=Field(default=None,min_length=3,max_length=3)
    axis_point_b_mm:list[float]|None=Field(default=None,min_length=3,max_length=3)
    lock_rotation:bool=False
    alignment:Literal['aligned','anti_aligned','closest']='closest'


class DesignSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    version:Literal[1]=1
    document:Literal['part','assembly']
    parts:list[PartSpec]=Field(min_length=1,max_length=12)
    instances:list[InstanceSpec]=Field(default_factory=list,max_length=24)
    mates:list[MateSpec]=Field(default_factory=list,max_length=60)
    allow_interference:bool=False
    allow_motion:bool=False

    @model_validator(mode='after')
    def validate_graph(self):
        parts={p.id for p in self.parts}
        if len(parts)!=len(self.parts):raise ValueError('Duplicate part ids')
        if self.document=='part':
            if len(parts)!=1 or self.instances or self.mates:raise ValueError('A part design has exactly one part and no mates')
            return self
        ids={i.id for i in self.instances}
        if len(ids)!=len(self.instances) or len(ids)<2:raise ValueError('Assembly needs at least two unique instances')
        if any(i.part_id not in parts for i in self.instances):raise ValueError('Unknown instance part')
        if {i.part_id for i in self.instances}!=parts:raise ValueError('Unused parts in assembly plan')
        fixed={i.id for i in self.instances if i.fixed}
        if len(fixed)!=1:raise ValueError('Choose exactly one fixed base component; locate the others with mates')
        if len({m.id for m in self.mates})!=len(self.mates):raise ValueError('Duplicate mate ids')
        for m in self.mates:
            if m.a not in ids or m.b not in ids or m.a==m.b:raise ValueError('Invalid mate reference')
            if m.kind=='concentric' and (m.radius_a_mm is None or m.radius_b_mm is None):raise ValueError('Concentric mates need explicit cylinder radii')
            if m.kind in {'coincident','distance'}:
                by_id={i.id:i for i in self.instances};a,b=by_id[m.a],by_id[m.b]
                na,nb=_plane_normal(a,m.plane_a),_plane_normal(b,m.plane_b)
                parallel=sum(x*y for x,y in zip(na,nb))
                signed=sum(n*(y-x) for n,x,y in zip(na,a.position_mm,b.position_mm))
                if abs(abs(parallel)-1)>1e-6:raise ValueError(f'Mate {m.id}: intended plane normals are not parallel')
                if m.alignment!='closest' and ((m.alignment=='aligned')!=(parallel>0)):
                    raise ValueError(f'Mate {m.id}: alignment contradicts intended rotation')
                target=m.distance_mm if m.kind=='distance' else 0
                if abs(abs(signed)-target)>1e-4:raise ValueError(f'Mate {m.id}: distance contradicts intended positions')
                if m.kind=='distance' and target>1e-4 and m.flip!=(signed<0):
                    raise ValueError(f'Mate {m.id}: flip must be {signed<0} for the signed intended plane distance')
        connected=set(fixed)
        for _ in self.instances:
            for m in self.mates:
                if m.a in connected or m.b in connected:connected.update((m.a,m.b))
        if connected!=ids:raise ValueError('Every moving component must be connected to the base by real mates')
        return self

    def stages(self):
        result=[{'kind':'part','id':p.id,'label':'创建零件 '+(p.label or p.id)} for p in self.parts]
        if self.document=='assembly':
            result.append({'kind':'assembly','label':'创建装配体并插入零件'})
            result += [{'kind':'mate','id':m.id,'label':'添加'+{'coincident':'重合','distance':'距离','concentric':'同心'}[m.kind]+'配合 '+m.id} for m in self.mates]
        return result+[{'kind':'check','label':'核对实际几何、配合与干涉'},{'kind':'delivery','label':'导出STEP、BOM与原生预览'}]


def skill_context():
    from .previews import view_specs,IDENTITY
    preview_views=list(view_specs(IDENTITY))
    """A small executable catalog, separate from unqualified upstream skill names."""
    return {
      'units':'mm; generated parts centered in XY, extend from z=0; shaft axis +Z; bracket profile XY extruded along +Z',
      'part_recipes':{'plate':'length,width,thickness; optional XY circular through holes (radius, not diameter)',
        'l_bracket':'length X,height Y,wall thickness; width is extrusion Z; holes follow the L profile',
        'shaft':'length along Z,diameter; plain cylinder',
        'enclosure':'length,width,height,wall; open top rectangular cavity; no lid unless a separate plate',
        'profile':'bounded native prism or revolve with exact profile points',
        'existing':'one uploaded SLDPRT source_id; preserve original; obtain dimensions from native inspection'},
      'assembly':'instances may repeat parts; exactly one fixed base, others positioned with actual coincident/distance/concentric mates; XY=Front,XZ=Top,YZ=Right; positions are intended final origins, Euler XYZ degrees; plane alignment defaults closest to preserve the intended orientation, can be aligned or anti_aligned for rotated brackets; concentric mates use radius and, when multiple equal cylinders exist, axis_point_a_mm/axis_point_b_mm in each part local coordinates',
      'plane_mate_math':'Origin-plane normals are XY=+Z, XZ=+Y, YZ=+X. Rotate each normal by the instance XYZ Euler matrix Rz*Ry*Rx. Selected plane normals must be parallel. Let signed=dot(rotated normal of plane_a, position_b-position_a). For distance mates distance_mm=abs(signed), flip=(signed<0); coincident requires signed=0. aligned means the two rotated normals point the same way, anti_aligned means opposite; closest preserves the intended orientation. The application rejects inconsistent geometry before any CAD write.',
      'native_design_workflow':{'tool':'solidworks_execute_design','status':'implemented and locally native-tested on SolidWorks2024',
        'execution':'The complete design is validated and staged by the application; the executor invokes this tool once. No separate tool names are required for the following built-in steps.',
        'built_in_checks':['create all native parts with fully defined sketches','insert repeated instances','add real coincident/distance/concentric mates','save and reopen the native assembly','read exact native bounds and volume','read actual mate entities and full constraint status','native interference detection','native STEP export and STEP reimport with body-count, bounds and volume checks'],
        'built_in_delivery':['SLDASM with dependent SLDPRT','STEP','BOM CSV',f"{len(preview_views)} native preview PNGs ({', '.join(preview_views)})",'dependency ZIP with geometry-verification.json and SHA256 hashes'],
        'preview_views':preview_views,
        'limits':'Static assemblies of the listed recipes; this does not certify load, manufacturing tolerances or motion.'},
      'editing':'Uploaded existing parts support true local dimension_changes: use exact name, before_value and unit from native dimension catalog, plus requested value. Preserve all other driving dimensions and features. Ambiguous dimension intent requires clarification. Parameter-less imported solids cannot be dimension-edited. For previous recipe designs, return a COMPLETE revised design preserving unspecified parts, dimensions and mates; create a new revision. Never overwrite originals.',
      'requirements':'ask only missing critical dimensions, interfaces, hole type and intended mating relationship; no arbitrary defaults for engineering parts; visual-only estimates require explicit user permission and assumptions',
      'edge_treatments':'Each part supports ordered constant-radius fillet and distance-angle chamfer operations. target=vertical_edges selects all straight Z-parallel edges; top_outer/bottom_outer select the sole extreme-Z planar face outer loop (exclude holes); hole_mouth requires exact hole_center_mm XYZ and hole_radius_mm. size_mm is radius or chamfer distance; angle_deg defaults45. expected_edges must match actual B-Rep before writing (4 vertical edges then 8 top perimeter edges for a four-corner-rounded plate). Read back actual native feature parameters after saving/reopening. No automatic radius reduction. Complex/multiple top faces require clarification or separate qualification.',
      'standard_holes':'standard_holes invokes the real ISO Hole Wizard: clearance ISO273, counterbore ISO4762, countersink ISO10642, tapped; M3/M4/M5/M6/M8/M10/M12. size is nominal screw size, not drill diameter. fit close/normal/loose for clearance families. point_mm is exact XYZ planar entry; outward is signed axis; depth_mm=null explicitly means Through All, otherwise cylindrical drill depth, with native drill point. Ask if hole family/termination is unclear. Tapped thread_representation=cosmetic uses standard manufacturing drill/callout; modeled creates a real native Thread with theoretical ISO carrier diameter and requires thread_depth_mm and local +Z entry. Compiler computes carrier diameter from the native nominal/pitch, do not ask user to calculate it. Specify thread_depth_mm to distinguish thread and drill lengths. Does not certify tolerance class.',
      'metric_threads':'metric_threads adds a real ISO metric coarse Thread to an existing full circular carrier: nominal-sized external shaft, or theoretical-minor-diameter internal bore D-1.08253175473*P. Local Z-axis, top/+Z entry only; provide exact point_mm and length_mm, right_handed. New internal tapped holes should use standard_holes kind=tapped,thread_representation=modeled, not duplicate metric_threads. New shafts use shape=shaft at nominal diameter with external metric_threads at z=length. Generic dimension_changes cannot edit Hole Wizard/Thread-managed dimensions. Native helix geometry verifies pitch and handedness; no cosmetic or polyline fallback for modeled requests.',
      'feature_order':'copy/edit driving dimensions; validate stock geometry; stock edge treatments; planar slots/pockets; standard holes; standalone metric threads; associative hole patterns; rebuild/save/reopen and verify every native definition and real geometry',
      'planar_cuts':'Part.planar_cuts supports native line/arc straight stadium slots and simple polygon pockets, only from the exact highest +Z planar face of one solid. Slot length_mm is TOTAL overall end-to-end length, including both round ends, not the arc-center spacing; center_mm=[x,y], width_mm, angle_deg, z_mm are required intent. Native arc-center spacing is length-width. Pockets use simple non-self-intersecting points_mm in model XY and exact z_mm. depth_mm=null is true Through All, otherwise flat-bottom blind depth strictly less than stock height. No intersection with prior voids, no edge breakout, no curved-face entry or arbitrary blended pockets. Stock fillets/chamfers run before cuts. App-created sketches need real driving constraints and zero Fix. Native cut definition, consumed sketch, exact top/bottom edge profiles, volume and STEP reimport are checked.',
      'native_standard_sketches':'The application creates fully constrained stock/position sketches without Fix. SOLIDWORKS Hole Wizard sections and library Thread profiles themselves may contain native Fix relations; these are native_standard_managed and remain editable through their standard feature, not generic sketch dimensions. Report actual native managed Fix counts separately, never claim every sketch has zero Fix and never remove native library constraints to fabricate that claim. Hole position at projected origin legitimately has zero independent coordinate dimensions but must have zero degrees of freedom and no Fix.',
      'thread_step_delivery':'Modeled threads require actual STEP reimport, exact body count/bounds/volume comparison and measured helical pitch/handedness from the reimported B-Rep. Native Thread blind depth and complete swept-profile axial range are reported separately; a partial end profile can extend beyond the helix depth. Do not claim manufacturing/full-thread engagement certification.',
      'associative_hole_patterns':'Part.hole_patterns creates native linear (including perpendicular 2D grids), full-circle circular and XZ/YZ mirror features from zero-based seed_hole_index in this same part standard_holes list. Seeds must be +Z clearance/counterbore/countersink holes. Count includes the seed. Circular needs center_mm=[x,y] and an existing unique cylindrical face there, usually an explicit central hole. Do not add separate holes for copies. Do not silently substitute manual copies. Model-space cylindrical axes, radii, axial ranges, seed linkage, exact removed volume and actual STEP reimport are checked. Tapped/modeled-thread seeds, body/component/offset-plane mirrors and arbitrary existing feature replication are not qualified by this route.',
      'not_yet_qualified':'fine/imperial/pipe/multiple-start or non-Z real threads, gears, variable-radius/face/full-round fillets, mechanisms, tolerance design and manufacturing drawings need separate qualification; do not silently omit requested features',
      'skills':['solidworks-vibecad','solidworks-automation/part','solidworks-automation/assembly','solidworks-automation/review']}
