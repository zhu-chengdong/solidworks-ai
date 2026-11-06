"""Read-only material-aware mass queries, including resolved flat assemblies."""
from __future__ import annotations
from types import SimpleNamespace as Obj
from .materials import measure, native_values, config
from .bom import summarize


def report(doc, density_kg_m3=None):
    # This MCP tool advertises readOnlyHint. Density changes belong to the
    # explicit material operation, never a measurement's optional argument.
    if density_kg_m3 is not None:
        raise ValueError('Mass queries are read-only; assign explicit density through Part.material before measuring')
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_measure import collect_mass_properties
    kind = int(get(doc, 'GetType'))
    if kind not in (1, 2):
        raise ValueError('Mass queries require a part or assembly')
    native = native_values(doc)
    legacy = collect_mass_properties(doc)
    if legacy.get('errors'):
        raise RuntimeError('Native mass-property query failed: ' + '; '.join(legacy['errors']))
    if kind == 1:
        physical = measure(doc)
        components = []
    else:
        actual = list(get(doc, 'GetComponents', True) or [])
        if not 1 <= len(actual) <= 200:
            raise ValueError('Read-only material qualification requires 1-200 resolved flat components')
        components = []
        for component in actual:
            part = get(component, 'GetModelDoc2')
            if part is None or int(get(part, 'GetType')) != 1:
                raise ValueError('Suppressed, unresolved or nested components need separate material qualification')
            referenced = str(get(component, 'ReferencedConfiguration'))
            if referenced != config(part):
                raise ValueError('Referenced configuration differs from the measured active configuration; no configuration was switched')
            physical_part = measure(part)
            components.append({'id':str(get(component, 'Name2')),
                'part_id':str(get(part, 'GetPathName')) + '@' + referenced,
                'physical_properties':physical_part})
        spec = Obj(instances=[Obj(id=row['id'], part_id=row['part_id']) for row in components])
        physical = summarize(spec, components, native['mass_g'])
        physical.update(material='Resolved component materials' if physical['mass_known'] else None,
            density_kg_m3=native['density_kg_m3'] if physical['mass_known'] else None,
            density_source='resolved_component_materials', volume_mm3=native['volume_mm3'])
    known = physical['mass_known']
    # Keep native surface area, centre and inertia. Replace the legacy
    # document-only material inference with independently verified mass.
    result = {**legacy, 'status':'ok' if known else 'warn',
        'mass_g':physical['mass_g'], 'mass_known':known,
        'volume_mm3':native['volume_mm3'],
        'density_kg_m3':physical['density_kg_m3'],
        'implied_density_kg_m3':native['density_kg_m3'] if known else None,
        'material':physical.get('material'), 'material_assigned':known,
        'material_assignment_scope':'resolved_components' if kind == 2 else 'part',
        'native_default_or_assigned_mass_g':native['mass_g'],
        'native_default_or_assigned_density_kg_m3':native['density_kg_m3'],
        'physical_properties':physical, 'components':components,
        'warnings':[] if known else [physical['note']], 'mass_accuracy':'maximum',
        'other_property_accuracy':'native_default', 'read_only':True,
        'engineering_intent_review_required':True}
    result.pop('suggestion', None)
    return result
