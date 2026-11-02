"""Opt-in live natural-language assembly and follow-up revision acceptance."""
import http.client,json,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    from workbench.settings import SettingsStore,ARTIFACT_ROOT
    from workbench.engine import WorkbenchEngine
    from workbench.jobs import JobManager
    from workbench.webserver import WorkbenchServer
    out=ROOT/'artifacts'/('EngineeringUI_'+time.strftime('%Y%m%d_%H%M%S'));out.mkdir()
    settings=SettingsStore();manager=JobManager(WorkbenchEngine(settings),ARTIFACT_ROOT)
    server=WorkbenchServer(('127.0.0.1',0),settings,manager);threading.Thread(target=server.serve_forever,daemon=True).start()
    def post(path,data,ctype='application/json',name='part.SLDPRT'):
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20)
        raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        client.request('POST',path,raw,headers={'X-App-Token':server.token,'Origin':server.origin,'Content-Type':ctype,'X-File-Name':name})
        response=client.getresponse();body=json.loads(response.read());client.close()
        if response.status>=400:raise RuntimeError(body.get('error','Request failed'))
        return body
    def wait(job):
        previous=None;deadline=time.monotonic()+900
        while manager.active and time.monotonic()<deadline:
            state=manager.get(job['id']);last=(state['phase'],state['events'][-1]['text'] if state['events'] else '')
            if last!=previous:print('ENGINEERING_UI '+json.dumps(last,ensure_ascii=False),flush=True);previous=last
            time.sleep(1)
        assert not manager.active,'Task is still active; do not retry writes'
        state=manager.get(job['id']);task=json.loads((Path(state['output_dir'])/'task.json').read_text(encoding='utf-8'))
        return state,task
    report={'computer_use':False,'cases':[]}
    try:
        job=post('/api/jobs',{'message':'创建两块相同的80×60×8毫米安装板，XY原点在板中心下表面，四孔中心在(±30,±20)毫米，孔径5.5毫米并贯穿。上下叠放，板面净间隙10毫米，孔轴对齐。底板固定，上板必须用真实配合定位，不要全部固定。保存装配体、全部零件、STEP和BOM，检查干涉并打包。'})
        state,task=wait(job);report['cases'].append({'case':'text_assembly','job':state,'tool_results':task['tool_results']})
        (out/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        design=task['plan'].get('design');assert design and design['document']=='assembly',state['summary']
        native=json.loads((Path(state['output_dir'])/'design-acceptance.json').read_text(encoding='utf-8'))
        assert native['status']=='passed',native.get('verification')
        job=post('/api/jobs',{'message':'把板面之间的净间隙改为15毫米，其他尺寸、孔位、组件数量和配合方式全部保持。另存新修订。','previous_job_id':state['id']})
        revised,task2=wait(job);report['cases'].append({'case':'natural_language_revision','job':revised,'tool_results':task2['tool_results']})
        assert task2['plan'].get('design'),revised['summary']
        check=json.loads((Path(revised['output_dir'])/'design-acceptance.json').read_text(encoding='utf-8'))
        assert check['status']=='passed',check.get('verification')
        positions=[c['position_mm'][2] for c in check['verification']['components']]
        assert abs(max(positions)-min(positions)-23)<.02,positions
        assert task['plan']['design']['parts']==task2['plan']['design']['parts'],'Revision changed unspecified part dimensions'
        report['status']='passed';print(json.dumps({'status':'passed','folder':str(out),'initial':state['id'],'revision':revised['id']},ensure_ascii=False))
    finally:
        (out/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not manager.active:server.shutdown();server.server_close();manager.pool.shutdown()


if __name__=='__main__':main()
