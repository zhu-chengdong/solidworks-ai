# Build on Windows x64. Both executables share one read-only dependency folder.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

root = Path(SPECPATH).parent
vendor = root / 'vendor' / 'solidworks-automation'
sys.path.insert(0, str(vendor))
reference_source = root / 'integrations/czuryk/source'
sys.path.insert(0, str(reference_source))
# A venv based on Conda otherwise omits libffi; official CPython needs no override.
conda_bin = Path(sys.base_prefix) / 'Library' / 'bin'
native_binaries = [(str(conda_bin/name), '.') for name in ('ffi.dll', 'sqlite3.dll')
                   if (conda_bin/name).is_file()]
datas = [(str(root / 'workbench' / 'web'), 'workbench/web')]
datas += collect_data_files('agents')
datas += [(str(reference_source / 'solidworks_mcp'), 'integrations/czuryk/source/solidworks_mcp'),
          (str(reference_source / 'LICENSE'), 'integrations/czuryk/source'),
          (str(root / 'integrations/czuryk/provenance.json'), 'integrations/czuryk')]
datas += [(str(file), str(Path('vendor/solidworks-automation') / file.relative_to(vendor).parent))
          for file in vendor.rglob('*') if file.is_file() and '__pycache__' not in file.parts
          and file.suffix not in {'.pyc', '.pyo'}]
for distribution in ('openai-agents', 'openai', 'mcp', 'httpx2', 'jsonschema', 'comtypes', 'pillow', 'pyyaml',
                     'numpy', 'scipy', 'opencv-python-headless', 'scikit-image', 'shapely', 'sympy','ezdxf','pypdfium2'):
    datas += copy_metadata(distribution, recursive=True)
hidden = collect_submodules('scripts') + collect_submodules('comtypes')
hidden += collect_submodules('solidworks_mcp.automation')
hidden += ['solidworks_mcp.utils']
hidden += ['win32cred', 'win32timezone', 'win32event', 'win32api', 'pythoncom', 'pywintypes',
           'win32com.client', 'artifact_access', 'http_transport',
           'apps.desktop.cad_workbench.queue_worker', 'release_tools.diagnostics', 'server']
a = Analysis([str(root / 'desktop_main.py')],
    pathex=[str(root), str(vendor), str(vendor / 'scripts'), str(vendor / 'mcp-server'), str(reference_source)],
    binaries=native_binaries, datas=datas, hiddenimports=hidden,
    excludes=['fitz', 'pymupdf', 'torch', 'transformers', 'matplotlib', 'pytest', 'IPython'],
    noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SolidWorksAI', console=False, upx=False)
mcp = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SolidWorksMCP', console=True, upx=False)
coll = COLLECT(gui, mcp, a.binaries, a.datas, strip=False, upx=False, name='SolidWorksAI')
