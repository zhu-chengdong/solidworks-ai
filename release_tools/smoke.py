"""Test the distributed ZIP from a relocated directory with no external Python PATH."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import zipfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('archive',type=Path)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    root=args.destination.resolve()
    root.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(args.archive) as archive:
        for member in archive.namelist():
            if not (root/member).resolve().is_relative_to(root):
                raise RuntimeError('Archive path escapes extraction directory')
        archive.extractall(root)
    program=root/'SolidWorksAI'/'SolidWorksAI.exe'
    data=root/'isolated user data'
    env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('API_KEY','SECRET','ACCESS_TOKEN'))
         and k.upper() not in {'PYTHONHOME','PYTHONPATH'}}
    windows=Path(os.environ.get('WINDIR',r'C:\Windows'))
    env['PATH']=os.pathsep.join(str(p) for p in [windows/'System32',windows,windows/'System32/WindowsPowerShell/v1.0'])
    env['SOLIDWORKS_AI_DATA_HOME']=str(data)
    diagnostic=data/'diagnostic.json'
    check=subprocess.run([str(program),'--diagnose',str(diagnostic)],cwd=root,env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,timeout=40)
    if check.returncode or not diagnostic.is_file():
        raise RuntimeError('Packaged diagnostic failed; inspect isolated user data')
    details=json.loads(diagnostic.read_text(encoding='utf-8'))
    if details.get('diagnostic_failed') or details.get('tools',0)<1:
        raise RuntimeError('Packaged MCP/native dependency diagnostic failed')
    ui=subprocess.Popen([str(program),'--no-browser'],cwd=root,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    origin=None
    try:
        instance=data/'runtime/workbench/instance.json'
        for _ in range(60):
            if instance.is_file():
                break
            if ui.poll() is not None:
                raise RuntimeError('Packaged UI exited before becoming ready')
            time.sleep(.25)
        config=json.loads(instance.read_text())
        origin=f"http://127.0.0.1:{config['port']}"
        with urllib.request.urlopen(origin+'/health',timeout=5) as response:
            health=json.load(response)
        with urllib.request.urlopen(origin+'/api/state',timeout=5) as response:
            state=json.load(response)
        with urllib.request.urlopen(origin,timeout=5) as response:
            page=response.read().decode('utf-8')
        token=re.search(r'name="app-token" content="([^"]+)"',page).group(1)
        second=subprocess.run([str(program),'--no-browser'],cwd=root,env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        if second.returncode or json.loads(instance.read_text())['pid']!=config['pid']:
            raise RuntimeError('Single-instance behavior failed')
        if not state['environment']['bundled'] or Path(state['environment']['data_directory'])!=data:
            raise RuntimeError('User data directory isolation failed')
        request=urllib.request.Request(origin+'/api/shutdown',data=b'{}',headers={
            'Content-Type':'application/json','X-App-Token':token,'Origin':origin},method='POST')
        with urllib.request.urlopen(request,timeout=5) as response:
            response.read()
        ui.wait(timeout=10)
        report={'status':'passed','tools':details['tools'],'native_modules_imported':details['native_modules_imported'],
            'credential_dummy_roundtrip_and_cleanup':details.get('credential_dummy_roundtrip_and_cleanup',False),
            'zip_extracted_and_relocated':True,'external_python_paths_removed':True,'ui_health':health,
            'user_data_isolated':True,'single_instance':True,'model_called':False,'cad_connected':False,
            'other_computer_tested':False}
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        if ui.poll() is None:
            ui.terminate()
            ui.wait(timeout=10)


if __name__=='__main__':
    main()
