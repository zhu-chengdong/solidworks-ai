"""Native, dimension-driven replacement for equation-curve reference sketches.

The pinned upstream source remains unchanged. This adapter uses the existing
host's sketch/feature helpers and its unmodified constraint checker.
"""
from __future__ import annotations

import math


def create_dimensioned_part(automation, spec, output, *, save_function=None):
    from scripts.sw_connect import get_com_member as get, create_empty_dispatch_variant, save_document
    from scripts.sw_part import sketch, sketch_line, sketch_circle, extrude_boss
    from scripts.sw_sketch_quality import fully_define_sketch, inspect_model_sketches

    made = automation.create_new_part()
    if not made.get('success'):
        raise RuntimeError(made.get('message', 'Cannot create native part'))
    doc = automation.app.ActiveDoc
    points = ([(float(x), float(y)) for x, y in spec.points] if spec.family == 'prism'
              else [(0., spec.points[0][0])] + [(r, axial) for axial, r in spec.points]
              + [(0., spec.points[-1][0])])
    with sketch(doc, 'Front Plane') as ref:
        sm = doc.SketchManager
        original_add = get(sm, 'AddToDB')
        lines = []
        try:
            sm.AddToDB = True
            for p, q in zip(points, points[1:] + points[:1]):
                line = sketch_line(doc, p[0]/1000, p[1]/1000, q[0]/1000, q[1]/1000)
                if line is None:
                    raise RuntimeError('Native profile line was not created')
                lines.append(line)
            for hole in spec.holes:
                if sketch_circle(doc, hole.x_mm/1000, hole.y_mm/1000, hole.radius_mm/1000) is None:
                    raise RuntimeError('Native hole circle was not created')
        finally:
            sm.AddToDB = original_add

        def constrain(entities, relation):
            doc.ClearSelection2(True)
            for entity in entities:
                if not entity.Select4(True, create_empty_dispatch_variant()):
                    raise RuntimeError('Cannot select native sketch entity')
            get(doc, 'SketchAddConstraints', relation)
            doc.ClearSelection2(True)

        # Create topology explicitly. Relying on screen inference left real DOFs
        # even when FullyDefineSketch returned 0 (its return value is undefined).
        for i, line in enumerate(lines):
            constrain([get(line, 'GetEndPoint2'), get(lines[(i+1) % len(lines)], 'GetStartPoint2')], 'sgCOINCIDENT')
            p, q = points[i], points[(i+1) % len(points)]
            if math.isclose(p[0], q[0], abs_tol=1e-10):
                constrain([line], 'sgVERTICAL')
            elif math.isclose(p[1], q[1], abs_tol=1e-10):
                constrain([line], 'sgHORIZONTAL')
        with automation.dimension_input_guard():
            initial_quality = fully_define_sketch(doc)

    if spec.family == 'prism':
        feature = extrude_boss(doc, ref, spec.depth_mm/1000, direction=False)
    else:
        from scripts.sw_part import _ensure_sketch_selected
        _ensure_sketch_selected(doc, ref)
        selection = get(doc.SelectionManager, 'CreateSelectData')
        selection.Mark = 16
        if not lines[-1].Select4(True, selection):
            raise RuntimeError('Cannot select revolve axis')
        feature = doc.FeatureManager.FeatureRevolve2(True, True, False, False, False, False,
            0, 0, math.tau, 0., False, False, 0., 0., 0, 0., 0., True, True, True)
    if feature is None:
        raise RuntimeError('Native dimensioned feature creation failed')
    feature.Name = 'ReferenceExtrude' if spec.family == 'prism' else 'ReferenceRevolve'
    if not get(doc, 'EditRebuild3'):
        raise RuntimeError('Native rebuild failed')
    quality = inspect_model_sketches(doc)
    if quality['status'] != 'pass':
        raise RuntimeError('Native consumed sketch constraint check did not pass')
    if not (save_function or save_document)(doc, str(output)):
        raise RuntimeError('Native part was not saved')
    return doc, {'compiler': 'native_dimensioned_v1', 'feature': str(get(feature, 'Name')),
                 'feature_type': str(get(feature, 'GetTypeName2')), 'sketch_quality': quality,
                 'initial_sketch_quality': initial_quality, 'no_fix_constraints': True}


def geometry_evidence(automation, doc, spec):
    from scripts.sw_connect import get_com_member as get
    bodies = automation._get_solid_bodies(doc)
    volume = sum(automation._body_mass_props(body, 'mm')['volume_exact'] for body in bodies)
    holes, vertices = [], []
    for body in bodies:
        for vertex in get(body, 'GetVertices') or []:
            vertices.append([float(v)*1000 for v in get(vertex, 'GetPoint')])
        if spec.family == 'prism':
            for face in get(body, 'GetFaces') or []:
                surface = get(face, 'GetSurface')
                if get(surface, 'IsCylinder'):
                    values = list(get(surface, 'CylinderParams'))
                    holes.append({'x_mm': values[0]*1000, 'y_mm': values[1]*1000,
                                  'radius_mm': values[6]*1000, 'axis': values[3:6]})
    expected = spec.expected_volume()
    volume_pass = len(bodies) == 1 and math.isclose(volume, expected, rel_tol=1e-6, abs_tol=1e-5)
    profile_pass = (all(any(math.hypot(v[0]-p[0], v[1]-p[1]) < 1e-4 for v in vertices) for p in spec.points)
                    if spec.family == 'prism' else None)
    holes_pass = len(holes) == len(spec.holes) and all(any(
        math.hypot(h['x_mm']-e.x_mm, h['y_mm']-e.y_mm) < 1e-4
        and abs(h['radius_mm']-e.radius_mm) < 1e-4 and abs(abs(h['axis'][2])-1) < 1e-6
        for h in holes) for e in spec.holes)
    return {'volume_mm3': volume, 'expected_volume_mm3': expected, 'body_count': len(bodies),
        'volume_verified': volume_pass, 'outline_vertices_verified': profile_pass,
        'cylindrical_holes': holes, 'holes_verified': holes_pass,
        'passed': volume_pass and holes_pass and profile_pass is not False}
