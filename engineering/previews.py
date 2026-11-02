"""Native model previews with one measured frame, camera readback and generations."""
import hashlib,json,math,re,zipfile
from pathlib import Path

LABELS={'isometric':'等轴测','front':'前视图','top':'俯视图','right':'右视图'}
IDENTITY=[1.,0.,0.,0.,1.,0.,0.,0.,1.]
def ensure_active_document(app,doc,get,activate):
    target=Path(get(doc,'GetPathName')).resolve()
    active=app.ActiveDoc
    if active is None or Path(get(active,'GetPathName')).resolve()!=target:activate(app,doc)
    active=app.ActiveDoc
    if active is None or Path(get(active,'GetPathName')).resolve()!=target:raise RuntimeError('Preview target document was not activated')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def reserve_preview_repair(directory):
    """Separate the per-task attempt limit from inherited image generations."""
    root=Path(directory).resolve();marker=root/'preview-repair-attempt.json'
    if marker.exists():raise ValueError('The single automatic preview repair was already attempted')
    generations=[0]
    for path in (root/'previews').glob('round-*'):
        match=re.fullmatch(r'round-(\d+)',path.name)
        if match:generations.append(int(match[1]))
    for path in root.iterdir():
        match=re.fullmatch(r'(?:CAD_delivery_preview_r|geometry-verification-preview-r|SHA256SUMS-preview-r)(\d+)\.(?:zip|json|txt)',path.name)
        if match:generations.append(int(match[1]))
    generation=max(generations)+1
    # Reserve before any native operation. A failed or interrupted call is not replayed.
    with marker.open('x',encoding='utf-8') as stream:json.dump({'generation':generation,'state':'attempted'},stream)
    return generation
def unit(v):
    n=math.sqrt(sum(x*x for x in v))
    if n<1e-10 or not math.isfinite(n):raise ValueError('Invalid preview direction')
    return [x/n for x in v]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def view_specs(rotation):
    if len(rotation)!=9:raise ValueError('Preview frame needs nine values')
    axes=[rotation[i:i+3] for i in (0,3,6)]
    if any(abs(sum(x*x for x in a)-1)>1e-5 for a in axes) or any(abs(sum(x*y for x,y in zip(axes[i],axes[j])))>1e-5 for i,j in [(0,1),(0,2),(1,2)]) or sum(x*y for x,y in zip(cross(axes[0],axes[1]),axes[2]))<.9999:
        raise ValueError('Preview frame is not a rigid right-handed rotation')
    def world(v):return [sum(rotation[c*3+r]*v[c] for c in range(3)) for r in range(3)]
    return {name:{'label':LABELS[name],'direction':world(direction),'up':world(up)} for name,direction,up in
        [('isometric',[-1,1,-1],[0,0,1]),('front',[0,1,0],[0,0,1]),('top',[0,0,-1],[0,1,0]),('right',[-1,0,0],[0,0,1])]}
def validate_camera(spec,actual):
    toward=unit([-x for x in spec['direction']]);right=unit(cross(spec['up'],toward));up=cross(toward,right)
    return all(len(actual.get(key,[]))==3 and max(abs(x-y) for x,y in zip(actual[key],target))<1e-5
               for key,target in [('right',right),('up',up),('toward_viewer',toward)])
def active_preview_entries(directory):
    root=Path(directory).resolve();path=root/'preview-manifest.json'
    if not path.exists():return None
    data=json.loads(path.read_text(encoding='utf-8'));views=data.get('views',[])
    if data.get('passed') is not True or {v.get('id') for v in views}!=set(LABELS) or len(views)!=4:raise ValueError('Incomplete preview manifest')
    for view in views:
        file=(root/view['file']).resolve()
        if not file.is_relative_to(root) or not file.is_file() or digest(file)!=view['sha256'] or not view['camera_verified'] or view['label']!=LABELS[view['id']]:raise ValueError('Preview manifest file/label/camera check failed')
    return views
def export_design_previews(automation,doc,directory,generation=0):
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_review import inspect_bmp_preview
    from PIL import Image
    from scripts.sw_assembly import _activate_model_document
    ensure_active_document(automation._sw_app,doc,get,_activate_model_document)
    root=Path(directory).resolve();folder=root/'previews'/f'round-{generation}'
    if folder.exists():raise ValueError('Preserve prior preview generation')
    rotation=IDENTITY;origin=[0.,0.,0.];source='part_local_axes'
    if int(get(doc,'GetType'))==2:
        fixed=[c for c in (get(doc,'GetComponents',True) or []) if bool(get(c,'IsFixed'))]
        if len(fixed)!=1:raise ValueError('Cannot choose preview frame without exactly one fixed base')
        transform=list(get(get(fixed[0],'Transform2'),'ArrayData'))
        if abs(transform[12]-1)>1e-6:raise ValueError('Scaled preview base is unsupported')
        rotation=transform[:9];origin=[v*1000 for v in transform[9:12]];source='measured_fixed_base:'+str(get(fixed[0],'Name2'))
    specs=view_specs(rotation);folder.mkdir(parents=True)
    views=[]
    for name,spec in specs.items():
        doc.ClearSelection2(True)
        result=automation.set_view_orientation(view_direction=spec['direction'],up_direction=spec['up'])
        if not result.get('success'):raise RuntimeError('Native camera assignment failed: '+name)
        _,actual=automation._active_view_state(doc)
        if not validate_camera(spec,actual):raise RuntimeError('Native camera readback failed: '+name)
        bmp=folder/(name+'.bmp');png=folder/(name+'.png')
        if not get(doc,'SaveBMP',str(bmp),1600,1000):raise RuntimeError('Native preview export failed: '+name)
        check=inspect_bmp_preview(bmp)
        if not check['exists'] or check.get('likely_blank',True):raise RuntimeError('Native preview is blank: '+name)
        with Image.open(bmp) as picture:picture.save(png)
        views.append({'id':name,'label':spec['label'],'file':png.relative_to(root).as_posix(),
            'sha256':digest(png),'camera_verified':True,'direction':spec['direction'],'up':spec['up'],'camera_basis':actual})
    automation.set_view_orientation(view_direction=specs['isometric']['direction'],up_direction=specs['isometric']['up'])
    data={'version':1,'generation':generation,'passed':True,'frame_source':source,'frame_rotation':rotation,'origin_mm':origin,
          'convention':'Fixed-base local X is horizontal, Z is screen-up for front/right; front looks +Y, right looks -X, top looks -Z with +Y screen-up.','views':views}
    (folder/'manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary=root/'preview-manifest.tmp';temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(root/'preview-manifest.json')
    return data

def repair_design_previews(app,output_dir,allowed_root):
    """One view-only correction, with immutable native file and ZIP checks."""
    from scripts.sw_connect import get_com_member as get,open_document
    from integrations.czuryk.native_only import native_automation
    from .package import build_delivery
    root=Path(allowed_root).resolve();out=Path(output_dir).resolve()
    if not out.is_relative_to(root):raise ValueError('Preview repair must stay inside the task root')
    record_path=out/'design-acceptance.json';record=json.loads(record_path.read_text(encoding='utf-8'))
    if not record['verification'].get('passed'):raise ValueError('Preview repair cannot bypass failed geometry')
    source_path=out/'preview-source.json';source=json.loads(source_path.read_text(encoding='utf-8')) if source_path.exists() else None
    doc_path=Path(record['active_path']).resolve()
    if not doc_path.is_relative_to(out):
        if not source or doc_path!=Path(source['active_path']).resolve() or not doc_path.is_relative_to(root):raise ValueError('Native repair document is outside the pinned source')
    protected={str(p.resolve()):digest(p) for p in out.rglob('*') if p.is_file() and p.suffix.lower() in {'.sldasm','.sldprt','.step','.stp','.zip'}}
    if source:
        for name,sha in source['files'].items():
            p=Path(name).resolve()
            if not p.is_relative_to(root) or digest(p)!=sha:raise ValueError('Pinned source model changed')
            protected[str(p)]=sha
    generation=reserve_preview_repair(out)
    doc=app.ActiveDoc
    if doc is None or Path(get(doc,'GetPathName')).resolve()!=doc_path:doc=open_document(app,str(doc_path),silent=True,raise_on_error=True)
    from scripts.sw_assembly import _activate_model_document
    ensure_active_document(app,doc,get,_activate_model_document)
    if int(get(doc,'GetType'))==2:
        from .native import _assembly_snapshot
        from .spec import DesignSpec
        actual=_assembly_snapshot(doc,DesignSpec.model_validate_json((out/'design-spec.json').read_text(encoding='utf-8')),record)
        if not actual['passed']:raise ValueError('Current assembly geometry changed; preview repair cannot bypass it')
    else:actual=record['verification']
    manifest=export_design_previews(native_automation(app),doc,out,generation=generation)
    if not all(digest(name)==sha for name,sha in protected.items()):raise RuntimeError('Native files changed while repairing views')
    files={out/name for name in record['package_hashes'] if Path(name).suffix.lower() in {'.sldasm','.sldprt','.step','.stp','.csv','.json'} and name not in {'geometry-verification.json','preview-manifest.json'}}
    files={p for p in files if p.is_file()};files.add(out/'preview-manifest.json');files.update(out/v['file'] for v in manifest['views'])
    evidence={'verification':record['verification'],'preview_manifest':manifest,'native_files_unchanged':True,'source_files':protected}
    package=build_delivery(out,out/f'CAD_delivery_preview_r{generation}.zip',files,evidence,evidence_stem=f'geometry-verification-preview-r{generation}',checksum_name=f'SHA256SUMS-preview-r{generation}.txt')
    record.update(package,preview_manifest=manifest,preview_paths=[str(out/v['file']) for v in manifest['views']])
    record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    receipt={'status':'passed','success':True,'preview_manifest':manifest,'native_files_unchanged':True,'verification_before_repair':actual,**package}
    (out/'preview-repair-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt
