"""Opt-in live test using a supplied airplane image and the existing local vault.

This spends the configured provider's API credits and operates SolidWorks natively.
It does not use browser/desktop automation or include credentials in its report.
"""
import argparse
import http.client
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('reference',type=Path)
    args=parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    from workbench.webserver import WorkbenchServer
    from workbench.engine import WorkbenchEngine
    from workbench.jobs import JobManager
    from workbench.settings import SettingsStore,ARTIFACT_ROOT
    out=ROOT/'artifacts'/('AircraftUI_'+time.strftime('%Y%m%d_%H%M%S'));out.mkdir()
    settings=SettingsStore()
    manager=JobManager(WorkbenchEngine(settings),ARTIFACT_ROOT)
    server=WorkbenchServer(('127.0.0.1',0),settings,manager)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def request(path,data,content_type='application/json'):
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=15)
        client.request('POST',path,data,headers={'X-App-Token':server.token,'Origin':server.origin,
            'Content-Type':content_type,'X-File-Name':'cartoon-airplane.png'})
        response=client.getresponse();body=json.loads(response.read());client.close()
        if response.status>=400:raise RuntimeError(body.get('error','Request failed'))
        return body
    report={'computer_use':False,'credential':'existing local vault; excluded from report'}
    try:
        reference=request('/api/uploads',args.reference.read_bytes(),'image/png')
        job=request('/api/jobs',json.dumps({'message':
            '按这张图创建三维卡通飞机，尺寸按比例估计，总长约160毫米。保留圆润白色机身、蓝色机腹、左右机翼、水平尾翼、垂尾、驾驶舱和每侧四个蓝色舷窗。隐藏面可以对称估计。只用原生API，保存可编辑SLDPRT和STEP并生成多视图预览。',
            'reference_ids':[reference['id']],'reference_mode':'approximate'}).encode())
        report['job_id']=job['id'];report['output_dir']=job['output_dir']
        (out/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        previous=None;deadline=time.monotonic()+1500
        while manager.active and time.monotonic()<deadline:
            state=manager.get(job['id']);latest=(state['phase'],state['events'][-1]['text'] if state['events'] else '')
            if latest!=previous:print('AIRCRAFT_UI '+json.dumps(latest,ensure_ascii=False),flush=True);previous=latest
            time.sleep(1)
        state=manager.get(job['id']);report.update(status=state['phase'],job=state)
        report['tool_results']=manager.jobs[job['id']].tool_results
        if manager.active:raise RuntimeError('Live workflow still active; inspect before retry')
        print(json.dumps({'status':state['phase'],'summary':state['summary'],'report':str(out/'acceptance.json')},ensure_ascii=False),flush=True)
    finally:
        (out/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not manager.active:
            server.shutdown();server.server_close();manager.pool.shutdown()


if __name__=='__main__':main()
