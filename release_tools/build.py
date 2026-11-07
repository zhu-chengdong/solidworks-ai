"""Build local release candidates from an explicit public source allowlist."""
from __future__ import annotations

import argparse
from importlib import metadata
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

if __package__:
    from .version_policy import require_source_version
else:
    from version_policy import require_source_version

ROOT = Path(__file__).resolve().parents[1]
FILES = ['app_runtime.py', 'desktop_main.py', 'server.py', 'agent.py',
         'launch-workbench.pyw', 'requirements-desktop.txt', 'requirements-reference.txt', 'providers.example.json',
         'integrations/__init__.py', 'integrations/czuryk/__init__.py',
         'integrations/czuryk/native_only.py', 'integrations/czuryk/reference_build.py',
         'integrations/czuryk/dimensioned.py',
         'integrations/czuryk/review_outputs.py',
         'integrations/czuryk/loft_spec.py', 'integrations/czuryk/loft_native.py',
         'integrations/czuryk/step_export.py',
         'integrations/czuryk/README.md',
         'integrations/czuryk/LOFT_REFERENCES.md',
         'integrations/czuryk/provenance.json', 'integrations/czuryk/source/LICENSE',
         'LICENSE', 'PATCHES.md', '.gitignore']
TREES = ['drawing2cad','workbench', 'engineering','tests', 'vendor/solidworks-automation', 'release_tools', 'patches', '.github',
         'integrations/czuryk/source/solidworks_mcp']
SENSITIVE = re.compile(r'\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|ms-[A-Za-z0-9_-]{24,}|org-[A-Za-z0-9]{16,}|proj_[A-Za-z0-9]{16,})\b')


def copy_public(destination):
    destination.mkdir(parents=True, exist_ok=False)
    paths = [ROOT / name for name in FILES]
    for tree in TREES:
        paths += [path for path in (ROOT/tree).rglob('*') if path.is_file()
                  and '__pycache__' not in path.parts and path.suffix not in {'.pyc','.pyo'}]
    for source in paths:
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise RuntimeError('Source path escapes public tree')
        relative = source.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(ROOT/'release_tools/README_EN_PUBLIC.md', destination/'README.md')
    shutil.copy2(ROOT/'release_tools/README_ZH_PUBLIC.md', destination/'README.zh-CN.md')
    shutil.copy2(ROOT/'release_tools/CHANGELOG_EN.md', destination/'CHANGELOG.md')
    shutil.copy2(ROOT/'release_tools/CHANGELOG.md', destination/'CHANGELOG.zh-CN.md')
    for name,old,new in [('CHANGELOG.md','(CHANGELOG.md)','(CHANGELOG.zh-CN.md)'),('CHANGELOG.zh-CN.md','(CHANGELOG_EN.md)','(CHANGELOG.md)')]:
        p=destination/name;p.write_text(p.read_text(encoding='utf8').replace(old,new),encoding='utf8')
    shutil.copy2(ROOT/'requirements-desktop.txt', destination/'requirements.txt')
    manifest = json.loads((ROOT/'vendor/source-manifest.json').read_text(encoding='utf-8'))
    manifest['source'] = 'https://github.com/wzyn20051216/solidworks-automation-skill'
    manifest['provenance_note'] = 'Original snapshot hashes; patched files described in PATCHES.md.'
    (destination/'vendor/source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    for path in destination.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {'.py','.cs','.md','.json','.yaml','.yml','.txt','.toml','.ps1','.html','.js','.css'}:
            continue
        content = path.read_text(encoding='utf-8-sig')
        normalized = content.replace('\\\\', '\\')
        personal_path = re.search(r'[A-Za-z]:\\Users\\(?!Public\b|Default\b|you\b|Example\b|YourName\b)[^\\\s"\']+', normalized, re.I)
        if SENSITIVE.search(content) or personal_path or re.search(r'[A-Za-z]:\\Research\\', normalized):
            raise RuntimeError('Public source needs review: '+str(path.relative_to(destination)))


def dependency_notices(bundle):
    licenses = bundle/'licenses'
    licenses.mkdir()
    dependencies = []
    # Only distributions actually included by PyInstaller; never all workstation packages.
    for info in sorted((bundle/'_internal').glob('*.dist-info')):
        package = metadata.PathDistribution(info)
        name = package.metadata['Name']
        target = licenses / info.name
        target.mkdir()
        for file in info.rglob('*'):
            if file.is_file() and file.name not in {'RECORD','direct_url.json'}:
                rel = file.relative_to(info)
                (target/rel).parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(file,target/rel)
        dependencies.append({'name':name,'version':package.version,
            'license_expression':package.metadata.get('License-Expression') or package.metadata.get('License','')[:300]})
    for name in ('LICENSE.txt','LICENSE_PYTHON.txt'):
        python_license = Path(sys.base_prefix)/name
        if python_license.is_file():
            shutil.copy2(python_license,licenses/('PYTHON-'+name))
    for notice in (ROOT/'release_tools/licenses').glob('*.txt'):
        shutil.copy2(notice,licenses/notice.name)
    for file in metadata.distribution('pyinstaller').files or []:
        if file.name in {'COPYING.txt','LICENSE'}:
            origin=metadata.distribution('pyinstaller').locate_file(file)
            if origin.is_file():
                shutil.copy2(origin,licenses/('PyInstaller-'+file.name))
    (bundle/'DEPENDENCIES.json').write_text(json.dumps(dependencies,indent=2),encoding='utf-8')


def archive(folder, path):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as zipped:
        for file in sorted(folder.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix not in {'.pyc','.pyo'}:
                zipped.write(file,Path(folder.name)/file.relative_to(folder))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tag',required=True)
    parser.add_argument('--source-only',action='store_true')
    args=parser.parse_args()
    try:
        require_source_version(args.tag, ROOT/'workbench/webserver.py')
    except ValueError as exc:
        parser.error(str(exc))
    release=ROOT/'releases'/args.tag
    release.mkdir(parents=True,exist_ok=False)
    source=release/'SolidWorksAI-source'
    copy_public(source)
    source_zip=release/f'SolidWorksAI-{args.tag}-source.zip'
    archive(source,source_zip)
    artifacts=[source_zip]
    if not args.source_only:
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm',
            '--distpath',str(release/'windows'),'--workpath',str(release/'build'),
            str(source/'release_tools/desktop.spec')],cwd=source,check=True)
        bundle=release/'windows'/'SolidWorksAI'
        for name,origin in [('README.md','README.md'),('LICENSE','LICENSE'),
            ('README.zh-CN.md','README.zh-CN.md'),('CHANGELOG.md','CHANGELOG.md'),('CHANGELOG.zh-CN.md','CHANGELOG.zh-CN.md'),
            ('THIRD_PARTY_NOTICES.md','release_tools/THIRD_PARTY_NOTICES.md')]:
            shutil.copy2(source/origin,bundle/name)
        dependency_notices(bundle)
        # Ensure source and optional copyleft PDF dependencies were not bundled by accident.
        if any((bundle/'_internal'/name).exists() for name in ('fitz','pymupdf')):
            raise RuntimeError('Optional PDF engine must not enter the basic bundle')
        windows_zip=release/f'SolidWorksAI-{args.tag}-windows-x64.zip'
        archive(bundle,windows_zip)
        artifacts.append(windows_zip)
    checksums=''.join(hashlib.sha256(file.read_bytes()).hexdigest()+'  '+file.name+'\n' for file in artifacts)
    (release/'SHA256SUMS.txt').write_text(checksums,encoding='ascii')
    print(json.dumps({'release':str(release),'artifacts':[str(file) for file in artifacts]}))


if __name__=='__main__':
    main()
