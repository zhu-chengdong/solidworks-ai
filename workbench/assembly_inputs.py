"""Bounded local assembly ZIPs; extract CAD documents only, never execute members."""
import hashlib,io,stat,zipfile
from pathlib import Path,PurePosixPath
from .settings import UserFacingError

MAX_ASSEMBLY_PARTS=12
MAX_ASSEMBLY_UNPACKED=200*1024*1024

def inspect_archive(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist()
            if len(entries)>128 or sum(i.file_size for i in entries)>MAX_ASSEMBLY_UNPACKED:
                raise ValueError('Archive limit')
            files=[];seen=set();basenames=set()
            for item in entries:
                normalized=item.filename.replace('\\','/');name=PurePosixPath(normalized)
                if (name.is_absolute() or any(p in {'..','.'} or ':' in p or p!=p.strip(' .') for p in normalized.rstrip('/').split('/'))
                        or normalized.casefold() in seen or item.flag_bits&1
                        or stat.S_ISLNK(item.external_attr>>16)):
                    raise ValueError('Unsafe member')
                seen.add(normalized.casefold())
                if item.is_dir():continue
                if item.file_size>50*1024*1024 or item.file_size>max(1,item.compress_size)*200:
                    raise ValueError('Member limit')
                if name.suffix.lower() not in {'.sldasm','.sldprt'}:continue
                if name.name.casefold() in basenames:raise ValueError('Ambiguous native basename')
                basenames.add(name.name.casefold());data=archive.read(item)
                native=data.startswith(bytes.fromhex('D0CF11E0A1B11AE1')) or (data[4:8]==bytes.fromhex('00000004') and data.find(bytes.fromhex('34F6E64756E64737F2'),8,2056)>=0)
                if not native:raise ValueError('Not native CAD')
                files.append({'member':item.filename,'relative':name.as_posix(),'name':name.name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            assemblies=[f for f in files if Path(f['name']).suffix.lower()=='.sldasm']
            parts=[f for f in files if Path(f['name']).suffix.lower()=='.sldprt']
            if len(assemblies)!=1 or not 1<=len(parts)<=MAX_ASSEMBLY_PARTS:raise ValueError('One flat assembly with bounded parts is required')
            return {'assembly':assemblies[0],'parts':parts,'files':files}
    except (ValueError,OSError,RuntimeError,zipfile.BadZipFile,NotImplementedError):
        raise UserFacingError('请提供包含一个SLDASM及完整SLDPRT依赖的ZIP；最多12种零件，不支持嵌套装配、重名零件或不安全的压缩包。') from None

def pin_archive(raw,folder):
    manifest=inspect_archive(raw);folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for item in manifest['files']:
            target=folder/item['relative']
            if not target.resolve().is_relative_to(folder):raise UserFacingError('装配依赖路径越界。')
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(archive.read(item['member']))
    return manifest
