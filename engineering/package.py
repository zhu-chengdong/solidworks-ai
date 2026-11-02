"""Self-contained CAD package with native evidence and verifiable file hashes."""
import hashlib,json,zipfile
from pathlib import Path


def build_delivery(output_dir,archive_path,files,evidence,*,evidence_stem='geometry-verification',checksum_name='SHA256SUMS.txt'):
    root=Path(output_dir).resolve();archive_path=Path(archive_path).resolve()
    if archive_path.parent!=root or archive_path.exists():raise ValueError('Preserve existing delivery; use a new archive name')
    paths={Path(p).resolve() for p in files}
    if any(not p.is_relative_to(root) or not p.is_file() for p in paths):raise ValueError('Delivery member is outside this task or missing')
    if Path(evidence_stem).name!=evidence_stem or Path(checksum_name).name!=checksum_name:raise ValueError('Invalid delivery evidence name')
    proof=root/(evidence_stem+'.json')
    if proof.exists():raise ValueError('Existing geometry evidence is preserved')
    proof.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8');paths.add(proof)
    hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    manifest=root/checksum_name
    if manifest.exists():raise ValueError('Existing checksum manifest is preserved')
    manifest.write_text(''.join(digest+'  '+name+'\n' for name,digest in hashes.items()),encoding='utf-8')
    paths.add(manifest);hashes[manifest.name]=hashlib.sha256(manifest.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as zipped:
        for p in sorted(paths):zipped.write(p,p.relative_to(root))
    with zipfile.ZipFile(archive_path) as zipped:
        if set(zipped.namelist())!=set(hashes):raise RuntimeError('ZIP member list differs from the delivery manifest')
        for name,digest in hashes.items():
            if hashlib.sha256(zipped.read(name)).hexdigest()!=digest:raise RuntimeError('ZIP readback hash mismatch')
    return {'package':str(archive_path),'package_verified':True,'package_entries':sorted(hashes),
        'package_hashes':hashes,'package_sha256':hashlib.sha256(archive_path.read_bytes()).hexdigest()}
