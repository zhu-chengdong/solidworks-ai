"""Checks for future regular releases; never imports or operates the CAD app."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re


def require_release_version(version):
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Use MAJOR.MINOR.PATCH without rc or other suffixes')
    return version


def require_source_version(version, path):
    require_release_version(version)
    tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    versions = [node.value.value for node in tree.body
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if versions != [version]:
        raise ValueError('Requested release and application VERSION must match')


def require_package_pair(folder, version):
    require_release_version(version)
    folder = Path(folder)
    names = [f'SolidWorksAI-{version}-{kind}.zip' for kind in ('source', 'windows-x64')]
    lines = [line.split() for line in (folder/'SHA256SUMS.txt').read_text(encoding='ascii').splitlines() if line.strip()]
    if len(lines) != 2 or any(len(line) != 2 for line in lines) or {line[1] for line in lines} != set(names):
        raise ValueError('Checksums must cover the matching source and Windows ZIP pair')
    checksums = {name: digest for digest, name in lines}
    for name in names:
        path = folder/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksums[name]:
            raise ValueError('Missing or changed release package: '+name)


def require_release_receipts(version, portable, proof):
    require_release_version(version)
    if portable.get('status') != 'passed' or portable.get('ui_health', {}).get('version') != version:
        raise ValueError('The actual tested Windows EXE must report this release version')
    if (proof.get('status') != 'passed' or proof.get('version') != version
            or proof.get('release_channel') != 'release'
            or proof.get('actual_stored_credentials_scan_passed') is not True
            or not any(t.get('bundled') for t in proof.get('trials', {}).values())):
        raise ValueError('Regular publication requires passed native/EXE and credential acceptance')
