"""BOM accounting from checked native instance properties, never default density."""
from __future__ import annotations
import math
from pathlib import Path

def summarize(spec, components, native_mass_g):
    expected={i.id:i.part_id for i in spec.instances}
    if len(components)!=len(expected) or {r['id']:r['part_id'] for r in components}!=expected:
        raise RuntimeError('Physical BOM instance list differs from the actual assembly')
    if not math.isfinite(native_mass_g) or native_mass_g<=0:raise RuntimeError('Invalid native assembly mass')
    unknown=[r['id'] for r in components if not r['physical_properties']['mass_known']]
    known=[r['physical_properties']['mass_g'] for r in components if r['physical_properties']['mass_known']]
    if any(v is None or not math.isfinite(v) or v<=0 for v in known):raise RuntimeError('Invalid known instance mass')
    subtotal=math.fsum(known);complete=not unknown
    if complete and not math.isclose(subtotal,native_mass_g,rel_tol=1e-6,abs_tol=.001):
        raise RuntimeError('Sum of actual instance masses disagrees with native assembly mass')
    return {'passed':True,'mass_known':complete,'mass_g':subtotal if complete else None,
        'known_subtotal_g':subtotal,'unknown_instances':unknown,'native_mass_g':native_mass_g,
        'native_total_verified':complete,'instance_count':len(components),
        'source':'maximum-accuracy native measurements per resolved instance',
        'note':None if complete else 'Total engineering mass is unknown until every instance has an assigned material or explicit verified density.'}

def rows(spec, parts, components):
    result=[]
    for part in spec.parts:
        instances=[r['physical_properties'] for r in components if r['part_id']==part.id]
        if not instances:raise RuntimeError('BOM contains an unused part')
        first=instances[0]
        for physical in instances[1:]:
            if (physical['material'],physical['density_kg_m3'],physical['mass_known'])!=(first['material'],first['density_kg_m3'],first['mass_known']):
                raise RuntimeError('Different material configurations cannot share a BOM row')
            if first['mass_known'] and not math.isclose(physical['mass_g'],first['mass_g'],rel_tol=1e-7,abs_tol=.0001):
                raise RuntimeError('Repeated part instances have unequal unit masses')
        known=first['mass_known'];quantity=len(instances)
        result.append({'part_id':part.id,'label':part.label,'quantity':quantity,'native_file':Path(parts[part.id]['path']).name,
            'material':first['material'] or '', 'density_kg_m3':first['density_kg_m3'] if known else '',
            'mass_state':'known' if known else 'unknown','unit_mass_g':first['mass_g'] if known else '',
            'total_mass_g':first['mass_g']*quantity if known else '',
            'density_source':first['density_source']})
    return result
