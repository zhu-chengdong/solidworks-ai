"""Immutable, local-only CAD attachments. Models receive metadata, not CAD bytes."""
import hashlib,json,re,uuid
from pathlib import Path
from .settings import UserFacingError

MAX_CAD_BYTES=50*1024*1024
MAX_CAD_FILES=12


class CadStore:
    def __init__(self,root):self.root=Path(root)

    def add(self,raw,name):
        name=Path(str(name).replace('\\','/')).name
        if Path(name).suffix.lower()=='.zip':
            if not 0<len(raw)<=MAX_CAD_BYTES:raise UserFacingError('装配依赖ZIP最多50MB。')
            from .assembly_inputs import inspect_archive
            manifest=inspect_archive(raw)
            self.root.mkdir(parents=True,exist_ok=True);asset=uuid.uuid4().hex;path=self.root/(asset+'.zip')
            path.write_bytes(raw)
            metadata={'id':asset,'name':name,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'kind':'assembly','part_count':len(manifest['parts'])}
            path.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf8')
            return metadata
        if Path(name).suffix.lower()!='.sldprt':raise UserFacingError('当前请选择SLDPRT零件；已有装配体需要完整依赖包。')
        if not 0<len(raw)<=MAX_CAD_BYTES:raise UserFacingError('每个零件文件最多50MB。')
        legacy=raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1'))
        # PRONOM fmt/1967: the 2015+ container is not OLE2. Native readback
        # subsequently verifies that the selected document really is a part.
        modern=raw[4:8]==bytes.fromhex('00000004') and raw.find(bytes.fromhex('34F6E64756E64737F2'),8,2056)>=0
        if not (legacy or modern):raise UserFacingError('文件不是可识别的SolidWorks零件容器。')
        self.root.mkdir(parents=True,exist_ok=True);asset=uuid.uuid4().hex;path=self.root/(asset+'.SLDPRT')
        path.write_bytes(raw)
        metadata={'id':asset,'name':name,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        path.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
        return metadata

    def resolve(self,ids):
        if not isinstance(ids,list) or len(ids)>MAX_CAD_FILES or len(set(ids))!=len(ids):raise UserFacingError('每个任务最多12个不同的零件文件。')
        result=[]
        for asset in ids:
            if not isinstance(asset,str) or not re.fullmatch('[a-f0-9]{32}',asset):raise UserFacingError('零件文件标识无效。')
            path=self.root/(asset+'.SLDPRT')
            if not path.is_file():path=self.root/(asset+'.zip')
            try:
                metadata=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                if hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['sha256']:raise ValueError('changed')
            except (OSError,ValueError,KeyError):raise UserFacingError('零件文件不可用，请重新选择。') from None
            result.append((path,metadata))
        return result


def pin_cad_inputs(job,files):
    if len(job.cad_inputs)+len(files)>MAX_CAD_FILES:raise UserFacingError('每个任务最多12个不同的零件文件。')
    mapping={}
    for source,metadata in files:
        if any(r['id']==metadata['id'] for r in job.cad_inputs):continue
        folder=job.output_dir/'inputs'/'cad';folder.mkdir(parents=True,exist_ok=True)
        suffix='.zip' if metadata.get('kind')=='assembly' else '.SLDPRT'
        target=folder/(metadata['id']+suffix);raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=metadata['sha256']:raise UserFacingError('零件文件已改变，请重新选择。')
        target.write_bytes(raw)
        item={**metadata,'file':target.relative_to(job.output_dir).as_posix()}
        if metadata.get('kind')=='assembly':
            from .assembly_inputs import pin_archive
            native_folder=folder/('assembly_'+metadata['id']);manifest=pin_archive(raw,native_folder)
            item['assembly_file']=(native_folder/manifest['assembly']['relative']).relative_to(job.output_dir).as_posix()
            item['documents']=[{'file':(native_folder/f['relative']).relative_to(job.output_dir).as_posix(),'name':f['name'],'sha256':f['sha256'],'size':f['size']} for f in manifest['files']]
        job.cad_inputs.append(item)
    for item in job.cad_inputs:mapping[item['id']]={'path':str(job.output_dir/item['file']),'sha256':item['sha256'],'name':item['name']}
    (job.output_dir/'cad-inputs.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
    job.save()
