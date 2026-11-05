"""Immutable local DXF/DWG/PDF uploads. Vector inputs never need an API key."""
import hashlib,io,json,re,uuid
from pathlib import Path
from .settings import UserFacingError

MAX_DRAWING_BYTES=20*1024*1024


class DrawingStore:
    def __init__(self,root,references):self.root=Path(root);self.references=references

    def add(self,raw,name):
        name=Path(str(name).replace('\\','/')).name;suffix=Path(name).suffix.lower()
        if suffix not in {'.dxf','.dwg','.pdf'}:raise UserFacingError('请选择DXF、DWG或PDF二维图纸。')
        if not 0<len(raw)<=MAX_DRAWING_BYTES:raise UserFacingError('每张图纸最多20MB。')
        if suffix=='.dwg' and not re.match(rb'AC10[0-9]{2}',raw[:6]):raise UserFacingError('文件不是有效的DWG容器。')
        if suffix=='.dxf' and not (raw.startswith(b'AutoCAD Binary DXF') or (b'SECTION' in raw[:8192] and b'HEADER' in raw[:8192])):raise UserFacingError('文件不是有效的DXF。')
        if suffix=='.pdf' and not raw.startswith(b'%PDF-'):raise UserFacingError('文件不是有效的PDF。')
        refs=[]
        if suffix=='.pdf':
            import pypdfium2 as pdfium
            try:
                with pdfium.PdfDocument(raw) as pdf:
                    if not 1<=len(pdf)<=4:raise UserFacingError('每份PDF支持1至4页，请只保留目标零件图。')
                    for i in range(len(pdf)):
                        page=pdf[i]
                        try:
                            width,height=page.get_size()
                            if not width>0 or not height>0:raise UserFacingError('PDF页面尺寸无效。')
                            bitmap=page.render(scale=min(2048/width,2048/height,3))
                            try:
                                buffer=io.BytesIO();bitmap.to_pil().save(buffer,format='PNG')
                                refs.append(self.references.add(buffer.getvalue(),name+' 第'+str(i+1)+'页'))
                            finally:bitmap.close()
                        finally:page.close()
            except UserFacingError:raise
            except Exception as exc:raise UserFacingError('PDF无法渲染，请检查密码保护或文件完整性。') from exc
        asset=uuid.uuid4().hex;self.root.mkdir(parents=True,exist_ok=True);path=self.root/(asset+suffix)
        path.write_bytes(raw)
        metadata={'id':asset,'name':name,'extension':suffix,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'kind':'pdf_image' if suffix=='.pdf' else 'vector','references':refs}
        path.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
        return metadata

    def resolve(self,ids):
        if not isinstance(ids,list) or len(ids)>1:raise UserFacingError('每个任务请选择一份二维图纸。')
        result=[]
        for asset in ids:
            if not isinstance(asset,str) or not re.fullmatch('[a-f0-9]{32}',asset):raise UserFacingError('图纸标识无效。')
            try:
                metadata=json.loads((self.root/(asset+'.json')).read_text(encoding='utf-8'))
                if metadata['extension'] not in {'.dxf','.dwg','.pdf'}:raise ValueError('extension')
                path=self.root/(asset+metadata['extension'])
                if hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['sha256']:raise ValueError('changed')
            except (OSError,ValueError,KeyError):raise UserFacingError('图纸已改变或不可用，请重新选择。') from None
            result.append((path,metadata))
        return result


def pin_drawings(job,files):
    for source,metadata in files:
        if any(d['id']==metadata['id'] for d in job.drawing_inputs):continue
        if job.drawing_inputs:raise UserFacingError('每个任务仅支持一份二维图纸。')
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=metadata['sha256']:raise UserFacingError('图纸校验失败。')
        folder=job.output_dir/'inputs'/'drawings';folder.mkdir(parents=True,exist_ok=True)
        target=folder/(metadata['id']+metadata['extension']);target.write_bytes(raw)
        job.drawing_inputs.append({**metadata,'file':target.relative_to(job.output_dir).as_posix()})
    job.save()

