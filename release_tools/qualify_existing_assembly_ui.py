"""Opt-in live test: local CAD picker -> native inspection -> model plan -> mates."""
import json,sys,time,threading,http.client,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    from workbench.settings import SettingsStore,ARTIFACT_ROOT
    from workbench.engine import WorkbenchEngine
    from workbench.jobs import JobManager
    from workbench.webserver import WorkbenchServer
    source=Path(sys.argv[1]).resolve();before=hashlib.sha256(source.read_bytes()).hexdigest()
    output=ROOT/'artifacts'/('ExistingAssemblyUI_'+time.strftime('%Y%m%d_%H%M%S'));output.mkdir()
    settings=SettingsStore();manager=JobManager(WorkbenchEngine(settings),ARTIFACT_ROOT)
    server=WorkbenchServer(('127.0.0.1',0),settings,manager);threading.Thread(target=server.serve_forever,daemon=True).start()
    def post(path,body,ctype='application/json'):
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20)
        client.request('POST',path,body,headers={'Content-Type':ctype,'X-App-Token':server.token,'Origin':server.origin,'X-File-Name':'mounting_plate.SLDPRT'})
        response=client.getresponse();data=json.loads(response.read());client.close()
        if response.status>=400:raise RuntimeError(data.get('error'))
        return data
    report={'computer_use':False,'cad_bytes_sent_to_model':False}
    try:
        ref=post('/api/cad-uploads',source.read_bytes(),'application/octet-stream')
        job=post('/api/jobs',json.dumps({'message':'请用我选择的孔板零件创建装配体，不改零件几何。这个零件使用两次，上下叠放，板面净间隙10毫米，各孔轴对齐，底板固定，上板用三个基准面配合完全定位。请自己读取零件的尺寸和原点，不要让我重复输入。保存所有依赖、STEP、BOM和交付包。','cad_ids':[ref['id']]}).encode())
        previous=None;deadline=time.monotonic()+900
        while manager.active and time.monotonic()<deadline:
            state=manager.get(job['id']);last=(state['phase'],state['events'][-1]['text'] if state['events'] else '')
            if previous!=last:print('EXISTING_ASSEMBLY '+json.dumps(last,ensure_ascii=False),flush=True);previous=last
            time.sleep(1)
        assert not manager.active,'Task still active; do not replay writes'
        state=manager.get(job['id']);task=json.loads((Path(state['output_dir'])/'task.json').read_text(encoding='utf-8'))
        report.update(job=state,tool_results=task['tool_results'])
        assert task['plan'].get('design'),state['summary']
        native=json.loads((Path(state['output_dir'])/'design-acceptance.json').read_text(encoding='utf-8'))
        assert native['status']=='passed',native['verification']
        assert hashlib.sha256(source.read_bytes()).hexdigest()==before
        assert all(p['shape']=='existing' for p in task['plan']['design']['parts'])
        report.update(status='passed',original_file_hash_unchanged=True)
        print(json.dumps({'status':'passed','report':str(output/'acceptance.json'),'output_dir':state['output_dir']},ensure_ascii=False))
    finally:
        (output/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not manager.active:server.shutdown();server.server_close();manager.pool.shutdown()


if __name__=='__main__':main()
