"""Native read-only inspection of an immutable, task-pinned input part."""
from pathlib import Path
import hashlib


def inspect_input(app,input_path,sha256,allowed_root):
    from scripts.sw_connect import get_com_member as get,open_document
    from scripts.sw_assembly import _activate_model_document
    from integrations.czuryk.native_only import native_automation
    path=Path(input_path).resolve();root=Path(allowed_root).resolve()
    if not path.is_relative_to(root) or path.parent.name!='cad' or path.parent.parent.name!='inputs' or path.suffix.lower()!='.sldprt':raise ValueError('Only task-pinned native part inputs can be inspected')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha256:raise ValueError('Input CAD bytes changed')
    previous=app.ActiveDoc;existing=app.GetOpenDocumentByName(str(path));doc=None
    try:
        doc=open_document(app,str(path),read_only=True,silent=True,raise_on_error=True)
        if int(get(doc,'GetType'))!=1:raise ValueError('Input is not a native part')
        a=native_automation(app);bodies=a._get_solid_bodies(doc);cylinders=[]
        if not bodies:raise ValueError('The selected part contains no solid body')
        for body in bodies:
            for face in get(body,'GetFaces') or []:
                surface=get(face,'GetSurface')
                if surface is not None and get(surface,'IsCylinder'):
                    values=list(get(surface,'CylinderParams'))
                    cylinders.append({'point_mm':[v*1000 for v in values[:3]],'axis':values[3:6],'radius_mm':values[6]*1000})
        from .native import _exact_bounds
        from .dimensions import catalog
        from .materials import measure
        bounds=_exact_bounds(bodies)
        return {'status':'ok','body_count':len(bodies),'volume_mm3':sum(a._body_mass_props(b,'mm')['volume_exact'] for b in bodies),
            'bounding_box_mm':bounds['min']+bounds['max'],'exact_bounds':bounds,'bounding_box_is_approximate':False,'cylindrical_faces':cylinders[:60],
            'principal_planes':'XY=Front Plane,XZ=Top Plane,YZ=Right Plane','source_sha256':sha256,'read_only':True,
            'editable_parameters':catalog(doc),'physical_properties':measure(doc)}
    finally:
        if doc is not None and existing is None:app.CloseDoc(str(get(doc,'GetTitle')))
        if previous is not None:_activate_model_document(app,previous)
