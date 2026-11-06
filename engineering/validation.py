"""Read actual mate entities and independently reimport assembly STEP geometry."""
import math
from pathlib import Path


def mate_readback(doc,spec,record):
    from .native import _get
    from scripts.sw_assembly import iter_feature_tree,get_component_feature
    planned={m.id:m for m in spec.mates};rows=[]
    for feature,_ in iter_feature_tree(doc,include_subfeatures=True):
        name=str(_get(feature,'Name'))
        if name not in planned:continue
        wanted=planned[name];mate=_get(feature,'GetSpecificFeature2');entities=[]
        for i in range(int(_get(mate,'GetMateEntityCount'))):
            entity=_get(mate,'MateEntity',i);component=_get(entity,'ReferenceComponent')
            row={'component':str(_get(component,'Name2')),'reference_type':int(_get(entity,'ReferenceType2')),
                'parameters_m':list(_get(entity,'EntityParams') or [])}
            try:row['reference_name']=str(_get(_get(entity,'Reference'),'Name'))
            except Exception:pass  # Cylinders and some plane proxies have no Name.
            if wanted.kind=='concentric':
                surface=_get(_get(entity,'Reference'),'GetSurface')
                if not _get(surface,'IsCylinder'):raise RuntimeError('Concentric mate lost its cylindrical reference')
                cylinder=list(_get(surface,'CylinderParams'));row['radius_mm']=cylinder[6]*1000
            else:
                plane=wanted.plane_a if row['component']==record['instances'][wanted.a] else wanted.plane_b
                selected=get_component_feature(component,{'XY':'Front Plane','XZ':'Top Plane','YZ':'Right Plane'}[plane])
                row['plane_verified']=row.get('reference_name')==str(_get(selected,'Name'))
            entities.append(row)
        distance=None
        if wanted.kind=='distance':
            display=_get(mate,'DisplayDimension2',0);dimension=_get(display,'GetDimension2',0)
            distance=float(_get(dimension,'SystemValue'))*1000
        expected_type={'coincident':0,'distance':5,'concentric':1}[wanted.kind]
        # ReferenceType2 uses swSelectType_e (face=2, datum plane=4),
        # unlike the obsolete ReferenceType mate-geometry enumeration.
        entity_type=2 if wanted.kind=='concentric' else 4
        ok=(int(_get(mate,'Type'))==expected_type and len(entities)==2 and
            {e['component'] for e in entities}=={record['instances'][wanted.a],record['instances'][wanted.b]} and
            all(e['reference_type']==entity_type for e in entities) and
            all((abs(e['radius_mm']-(wanted.radius_a_mm if e['component']==record['instances'][wanted.a] else wanted.radius_b_mm))<1e-4)
                if wanted.kind=='concentric' else e['plane_verified'] for e in entities) and
            (distance is None or abs(distance-wanted.distance_mm)<1e-4))
        rows.append({'name':name,'type':int(_get(mate,'Type')),'entities':entities,'distance_mm':distance,'verified':ok})
    return {'passed':len(rows)==len(planned) and all(r['verified'] for r in rows),'mates':rows}


def verify_assembly_step(app,doc,step,verification,expected_bodies,geometry_validator=None,geometry_label='thread_geometry'):
    from .native import _get,_exact_bounds,_atomic
    from scripts.sw_connect import open_document
    from scripts.sw_assembly import _activate_model_document
    from scripts.sw_measure import collect_mass_properties
    from solidworks_mcp.automation.com_utils import resolve_solidworks_constant as constant
    import pythoncom,win32com.client
    def precise_volume(model):
        # STEP spline faces can have a different default integration accuracy
        # from native analytic faces. Compare both at the documented maximum
        # accuracy instead of relaxing the existing geometry tolerance.
        status=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        values=list(model.Extension.GetMassProperties2(2,status,False) or [])
        if status.value!=0 or len(values) not in (12,13) or not math.isfinite(values[3]) or values[3]<=0:
            raise RuntimeError('Maximum-accuracy native volume measurement failed')
        if len(values)==13 and values[12]!=2:raise RuntimeError('Native volume did not use maximum accuracy')
        return values[3]*1e9
    native_volume=precise_volume(doc)
    snapshot_volume=verification['mass_properties']['volume_mm3']
    if not math.isclose(native_volume,snapshot_volume,rel_tol=1e-5,abs_tol=.01):
        raise RuntimeError('Native volume changed since the verified snapshot')
    # Distinct name prevents SolidWorks reusing an already open native document.
    folder=Path(step).parent/'validation';folder.mkdir(exist_ok=True)
    source=folder/('reimport_'+Path(step).name);source.write_bytes(Path(step).read_bytes())
    native_path=str(_get(doc,'GetPathName'));task=Path(native_path).parent
    old_directory=str(_get(app,'GetCurrentWorkingDirectory'))
    # The classic geometry-only importer avoids new-document and per-component
    # conversion prompts from 3D Interconnect. Restore every option afterwards.
    options={'swMultiCAD_Enable3DInterconnect':False,'swImportStepConfigData':False,
        'swImportMultBodyAsPartData':False,'swImportAutoRunImportDiagnostics':False,
        'swImportAutoRunImportDiagnosticsPersist':True,'swImportNeutralRunDiagnostics':False}
    before={constant(name):bool(_get(app,'GetUserPreferenceToggle',constant(name))) for name in options}
    mapping_id=constant('swImportNeutralAssemblyStructureMapping')
    old_mapping=int(_get(app,'GetUserPreferenceIntegerValue',mapping_id))
    _atomic(folder/'import-settings.json',{'native_path':native_path,'working_directory':old_directory,
        'toggles':before,'integer_values':{mapping_id:old_mapping},'restored':False})
    owned=[]
    for current in _get(app,'GetDocuments') or []:
        path=str(_get(current,'GetPathName'))
        if path and Path(path).resolve().is_relative_to(task):owned.append((str(_get(current,'GetTitle')),int(_get(current,'GetType'))))
    # AP214 carries product names internally, so a different .step filename
    # alone does not avoid collisions with its open native product documents.
    for title,_ in sorted(owned,key=lambda item:item[1],reverse=True):app.CloseDoc(title)
    imported=None
    try:
        for name,value in options.items():
            preference=constant(name);_get(app,'SetUserPreferenceToggle',preference,value)
            if bool(_get(app,'GetUserPreferenceToggle',preference))!=value:raise RuntimeError('Cannot set bounded import option '+name)
        mapping=constant('swImportNeutralAssemblyStructureMapping_MultibodyPart')
        _get(app,'SetUserPreferenceIntegerValue',mapping_id,mapping)
        if int(_get(app,'GetUserPreferenceIntegerValue',mapping_id))!=mapping:raise RuntimeError('Cannot select geometry-only STEP verification')
        if not _get(app,'SetCurrentWorkingDirectory',str(folder)):raise RuntimeError('Cannot contain native STEP import outputs in the task folder')
        imported=open_document(app,str(source),silent=True,raise_on_error=True)
        kind=int(_get(imported,'GetType'));bounds=[];count=0
        if kind==1:
            bodies=list(_get(imported,'GetBodies2',0,False) or []);count=len(bodies);bounds.append(_exact_bounds(bodies))
        elif kind==2:
            for component in _get(imported,'GetComponents',False) or []:
                model=_get(component,'GetModelDoc2')
                if model is None or int(_get(model,'GetType'))!=1:continue
                bodies=list(_get(model,'GetBodies2',0,False) or []);count+=len(bodies)
                transform=list(_get(_get(component,'Transform2'),'ArrayData'))
                bounds.append(_exact_bounds(bodies,transform))
        else:raise RuntimeError('STEP reimport did not yield a part or assembly')
        if not count:raise RuntimeError('Assembly STEP reimport contains no solid geometry')
        actual={'min':[min(b['min'][i] for b in bounds) for i in range(3)],
                'max':[max(b['max'][i] for b in bounds) for i in range(3)]}
        actual['size_mm']=[b-a for a,b in zip(actual['min'],actual['max'])]
        mass=collect_mass_properties(imported);volume=precise_volume(imported)
        wanted=verification['exact_bounds'];expected_volume=native_volume
        passed=(count==expected_bodies and not mass.get('errors') and
            math.isclose(volume,expected_volume,rel_tol=1e-5,abs_tol=.01) and
            all(abs(a-b)<.01 for k in ('min','max') for a,b in zip(actual[k],wanted[k])))
        result={'passed':passed,'reimported_body_count':count,'expected_bodies':expected_bodies,
                'volume_mm3':volume,'expected_volume_mm3':expected_volume,'exact_bounds':actual,
                'native_reimport':True,'geometry_only':True,'volume_accuracy':'maximum',
                'default_imported_volume_mm3':mass['volume_mm3'],'snapshot_volume_mm3':snapshot_volume}
        if not passed:raise RuntimeError('Assembly STEP reimport differs from the native instance geometry: '+str(result))
        if geometry_validator is not None:
            result[geometry_label]=geometry_validator(imported)
            if not result[geometry_label]['passed']:raise RuntimeError('Reimported STEP feature geometry failed')
        return result
    finally:
        if imported is not None:app.CloseDoc(str(_get(imported,'GetTitle')))
        _get(app,'SetCurrentWorkingDirectory',old_directory)
        for preference,value in before.items():_get(app,'SetUserPreferenceToggle',preference,value)
        _get(app,'SetUserPreferenceIntegerValue',mapping_id,old_mapping)
        if any(bool(_get(app,'GetUserPreferenceToggle',preference))!=value for preference,value in before.items()) or int(_get(app,'GetUserPreferenceIntegerValue',mapping_id))!=old_mapping:
            raise RuntimeError('Import preferences could not be restored')
        restored=open_document(app,native_path,silent=True,raise_on_error=True)
        _activate_model_document(app,restored)
        _atomic(folder/'import-settings.json',{'restored':True,'native_path':native_path,'working_directory':old_directory,
            'toggles':before,'integer_values':{mapping_id:old_mapping}})
