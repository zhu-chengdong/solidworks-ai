"""Report native library profiles separately; never erase their Fix counts."""
from copy import deepcopy


def classify(raw,holes,threads):
    result=deepcopy(raw);result['raw_status']=raw['status'];owners=set();positions=set()
    for row in holes:
        native=row['native']
        if not native.get('passed'):continue
        owners.add(native['feature']);positions.add(native['position']['sketch_name'])
        if native.get('thread',{}).get('passed'):owners.add(native['thread']['feature'])
    owners.update(row['native']['feature'] for row in threads if row['native'].get('passed'))
    managed=[];application=[]
    for sketch in result['sketches']:
        sketch['raw_status']=sketch['status']
        consumed=set(sketch.get('consumed_by',[]))
        if consumed & owners and sketch['name'] not in positions:
            if sketch['constrained_status']==3 and sketch.get('dangling') is False:
                sketch.update(status='native_standard_managed',managed_by=sorted(consumed & owners))
                managed.append(sketch);continue
        if sketch['name'] in positions and sketch['constrained_status']==3 and sketch['fix_count']==0 and sketch.get('dangling') is False:
            sketch['status']='pass'
        application.append(sketch)
    result['application_sketches_pass']=bool(application) and all(s['status']=='pass' and s['fix_count']==0 for s in application)
    result['native_managed_profile_count']=len(managed)
    result['native_managed_profile_fix_count']=sum(s['fix_count'] or 0 for s in managed)
    result['application_fix_count']=sum(s['fix_count'] or 0 for s in application)
    if result['application_sketches_pass'] and len(application)+len(managed)==len(result['sketches']):
        result['status']='native_standard_profiles_verified' if managed else 'pass'
    else:result['status']='review_required'
    return result


def inspect(doc,holes,threads):
    from scripts.sw_sketch_quality import inspect_model_sketches
    return classify(inspect_model_sketches(doc),holes,threads)
