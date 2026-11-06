"""Native material assignment, explicit density and verified physical properties."""
from __future__ import annotations
import math,hashlib,xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

ALIASES={
 'aluminium_6061':('6061 Alloy','6061 合金'),
 'aluminium_6061_t6':('6061-T6 (SS)',),
 'stainless_316_sheet':('AISI 316 Stainless Steel Sheet (SS)','AISI 316 不锈钢板 (SS)'),
 'stainless_316_bar':('AISI 316 Annealed Stainless Steel Bar (SS)','AISI 316 退火不锈钢条 (SS)'),
 'plain_carbon_steel':('Plain Carbon Steel','普通碳钢'),
 'abs':('ABS',)}

class MaterialSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    grade:Literal['aluminium_6061','aluminium_6061_t6','stainless_316_sheet','stainless_316_bar','plain_carbon_steel','abs','custom_density']
    label:str|None=Field(default=None,min_length=1,max_length=100)
    density_kg_m3:float|None=Field(default=None,gt=0,le=30000)
    @model_validator(mode='after')
    def explicit(self):
        if self.grade=='custom_density':
            if self.label is None or not self.label.strip() or self.density_kg_m3 is None:raise ValueError('Custom density requires an explicit material label and kg/m3 value')
        elif self.label is not None or self.density_kg_m3 is not None:raise ValueError('Standard material name and density come from the actual installed library')
        return self

def config(doc):
    from scripts.sw_connect import get_com_member as get
    return str(get(get(doc.ConfigurationManager,'ActiveConfiguration'),'Name'))

def identity(doc):
    from solidworks_mcp.automation.com_utils import typed
    raw=typed(doc,'IPartDoc').GetMaterialPropertyName2(config(doc))
    if isinstance(raw,(list,tuple)):
        if len(raw)!=2:raise RuntimeError('Unexpected native material identity result')
        name,database=raw
    else:raise RuntimeError('Native material identity requires material and database readback')
    return {'name':str(name or ''),'database':str(database or ''),'configuration':config(doc)}

def library(app,spec):
    from scripts.sw_connect import get_com_member as get
    from integrations.czuryk.native_only import registered_executable
    paths=[Path(p) for p in get(app,'GetMaterialDatabases') or []]
    lang=registered_executable().parent/'lang'
    paths += [lang/name/'sldmaterials/solidworks materials.sldmat' for name in ('english','chinese-simplified')]
    unique=[]
    for path in paths:
        if path.suffix.lower()=='.sldmat' and path.is_file() and str(path.resolve()).casefold() not in [str(p.resolve()).casefold() for p in unique]:unique.append(path)
    # Prefer the installed standard library; configured custom libraries remain
    # discoverable but cannot silently shadow a standard alias.
    unique.sort(key=lambda p:(p.name.casefold()!='solidworks materials.sldmat',not p.resolve().is_relative_to(lang.resolve())))
    for path in unique:
        matches=[]
        for material in ET.parse(path).iter():
            if material.tag.split('}')[-1]!='material' or material.attrib.get('name') not in ALIASES[spec.grade]:continue
            densities=[float(p.attrib['value']) for p in material.iter() if p.tag.split('}')[-1]=='DENS']
            if len(densities)!=1 or not math.isfinite(densities[0]) or densities[0]<=0:raise ValueError('Installed material has no unambiguous density')
            matches.append({'name':material.attrib['name'],'database':str(path.resolve()),'database_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'density_kg_m3':densities[0]})
        if len(matches)>1:raise ValueError('Installed library has ambiguous standard material aliases')
        if matches:return matches[0]
    raise ValueError('Requested material is absent from the actual installed libraries; no density-only fallback')

def native_values(doc):
    import pythoncom,win32com.client
    status=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    values=list(doc.Extension.GetMassProperties2(2,status,False) or [])
    if status.value!=0 or len(values) not in (12,13) or values[3]<=0 or values[5]<=0 or not all(math.isfinite(v) for v in values):raise RuntimeError('Native maximum-accuracy mass/volume measurement failed')
    if len(values)==13 and values[12]!=2:raise RuntimeError('Native mass calculation did not use maximum accuracy')
    return {'volume_mm3':values[3]*1e9,'mass_g':values[5]*1000,'density_kg_m3':values[5]/values[3],'accuracy':'maximum'}

def measure(doc):
    from scripts.sw_document_data import read_custom_property
    native=identity(doc);physical=native_values(doc)
    volume=physical['volume_mm3'];mass=physical['mass_g'];rho=physical['density_kg_m3']
    mode=read_custom_property(doc,'SWAI_MaterialMode',configuration_name=native['configuration'])
    known=bool(native['name']);label=native['name'] or None;source='native_library_assignment' if known else 'unassigned_native_default'
    if not known and mode['exists'] and mode['raw']=='custom_density':
        marker=read_custom_property(doc,'SWAI_DensityKgM3',configuration_name=native['configuration']);label_prop=read_custom_property(doc,'SWAI_MaterialLabel',configuration_name=native['configuration'])
        try:requested=float(marker['raw'])
        except (ValueError,TypeError):requested=float('nan')
        known=bool(label_prop['exists'] and label_prop['raw'] and math.isfinite(requested) and math.isclose(rho,requested,rel_tol=1e-7,abs_tol=1e-4))
        if known:label=label_prop['raw'];source='explicit_custom_density'
    return {'material':label,'material_name':native['name'] or None,'database':native['database'] or None,'configuration':native['configuration'],
        'mass_known':known,'mass_g':mass if known else None,'density_kg_m3':rho if known else None,'volume_mm3':volume,
        'native_default_or_assigned_mass_g':mass,'native_default_or_assigned_density_kg_m3':rho,'density_source':source,'accuracy':'maximum',
        'note':None if known else 'Unassigned material is not a known engineering mass; the native default reading is retained separately.'}

def apply(app,doc,spec):
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_document_data import set_custom_properties
    from solidworks_mcp.automation.com_utils import typed,resolve_solidworks_constant
    before=measure(doc)
    if spec is None:return {'requested':None,'before':before,'actual':before,'passed':True,'geometry_preserved':True}
    part=typed(doc,'IPartDoc');configuration=config(doc)
    if spec.grade=='custom_density':
        # The density preference belongs to the document. Until configuration
        # isolation has its own acceptance, do not change a multi-config file.
        if len(get(doc,'GetConfigurationNames') or [])!=1:raise ValueError('Custom density changes require a single-configuration part')
        expected={'name':'','database':'','density_kg_m3':spec.density_kg_m3,'label':spec.label}
        part.SetMaterialPropertyName2(configuration,'','')
        if identity(doc)['name']:raise RuntimeError('Native material was not cleared before setting custom density')
        if not doc.SetUserPreferenceDoubleValue(resolve_solidworks_constant('swMaterialPropertyDensity'),spec.density_kg_m3):raise RuntimeError('Native custom density setter failed')
        props={'SWAI_MaterialMode':'custom_density','SWAI_MaterialLabel':spec.label,'SWAI_DensityKgM3':str(spec.density_kg_m3)}
    else:
        expected=library(app,spec);part.SetMaterialPropertyName2(configuration,expected['database'],expected['name'])
        props={'SWAI_MaterialMode':'library','SWAI_MaterialLabel':expected['name'],'SWAI_DensityKgM3':str(expected['density_kg_m3'])}
    written=set_custom_properties(doc,props,configuration_name=configuration)
    if not written['success']:raise RuntimeError('Native material provenance properties did not persist')
    if not get(doc,'ForceRebuild3',False):raise RuntimeError('Material change rebuild failed')
    after=measure(doc)
    material_ok=after['material_name']==(expected['name'] or None)
    # GetMaterialPropertyName2 returns the installed database's display stem
    # (for example 'solidworks materials'), although the setter accepts its
    # absolute .sldmat path. Verify that exact native identifier together with
    # the selected material name and independently read actual mass/density.
    if expected['name']:material_ok=material_ok and Path(str(after['database'])).stem.casefold()==Path(expected['database']).stem.casefold()
    preserved=math.isclose(before['volume_mm3'],after['volume_mm3'],rel_tol=1e-9,abs_tol=.001)
    valid=material_ok and after['mass_known'] and math.isclose(after['density_kg_m3'],expected['density_kg_m3'],rel_tol=1e-7,abs_tol=1e-4) and preserved
    if not valid:raise RuntimeError('Assigned material identity, actual density/mass or preserved geometry did not verify')
    return {'requested':spec.model_dump(),'expected':expected,'before':before,'actual':after,'passed':True,'geometry_preserved':preserved}

def refresh(doc,record):
    """Keep verified material identity while planned CAD operations alter volume."""
    actual=measure(doc);wanted=record['actual']
    keys=('mass_known','material_name','material','database','configuration','density_source')
    same=all(actual[k]==wanted[k] for k in keys)
    if wanted['mass_known']:same=same and math.isclose(actual['density_kg_m3'],wanted['density_kg_m3'],rel_tol=1e-7,abs_tol=1e-4)
    if not same:raise RuntimeError('Material identity or density changed during planned CAD operations')
    return {**record,'assignment_actual_before_model_operations':wanted,'actual':actual}

def verify(doc,record):
    actual=measure(doc);wanted=record['actual']
    preserved=actual['mass_known']==wanted['mass_known'] and actual['material_name']==wanted['material_name'] and actual['material']==wanted['material'] and actual['database']==wanted['database'] and actual['configuration']==wanted['configuration'] and actual['density_source']==wanted['density_source'] and math.isclose(actual['volume_mm3'],wanted['volume_mm3'],rel_tol=1e-8,abs_tol=.001)
    if wanted['mass_known']:preserved=preserved and math.isclose(actual['mass_g'],wanted['mass_g'],rel_tol=1e-7,abs_tol=1e-4) and math.isclose(actual['density_kg_m3'],wanted['density_kg_m3'],rel_tol=1e-7,abs_tol=1e-4)
    if not preserved:raise RuntimeError('Saved material or measured physical properties changed after reopening')
    return {'passed':True,'actual':actual,'geometry_preserved':True}
