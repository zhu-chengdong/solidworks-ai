"""Opt-in live acceptance: HTTP upload -> vision plan -> MCP native part -> review."""
import http.client
import json
from pathlib import Path
import re
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    from PIL import Image, ImageDraw, ImageFont
    from workbench.webserver import WorkbenchServer
    from workbench.engine import WorkbenchEngine
    from workbench.jobs import JobManager
    from workbench.settings import SettingsStore
    output=ROOT/'artifacts'/('ReferenceUI_'+time.strftime('%Y%m%d_%H%M%S'))
    output.mkdir(parents=True,exist_ok=False)
    complex_fixture = '--complex' in sys.argv
    fixture=output/'reference.png'
    if complex_fixture:
        from release_tools.reference_fixture import stepped_plate_image
        stepped_plate_image(fixture)
    else:
        image=Image.new('RGB',(900,700),'white');draw=ImageDraw.Draw(image)
        font=ImageFont.truetype('arial.ttf',24)
        draw.polygon([(200,550),(680,550),(680,430),(320,430),(320,190),(200,190)],fill='#e6edf4',outline='black',width=3)
        for xy,text in [((330,575),'Overall width = 40 mm'),((350,135),'Overall height = 30 mm'),
                        ((360,350),'Leg width = 10 mm'),((360,390),'Uniform thickness = 8 mm'),
                        ((220,50),'L profile, front view. Extrude normal to page.')]:
            draw.text(xy,text,fill='black',font=font)
        image.save(fixture)
    settings=SettingsStore()
    manager=JobManager(WorkbenchEngine(settings),output/'jobs')
    server=WorkbenchServer(('127.0.0.1',0),settings,manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(path,data,content_type='application/json'):
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=15)
        client.request('POST',path,data,headers={'X-App-Token':server.token,'Origin':server.origin,
            'Content-Type':content_type,'X-File-Name':'reference.png'})
        response=client.getresponse();body=json.loads(response.read());client.close()
        if response.status>=400:raise RuntimeError(body.get('error','Request failed'))
        return body
    report={'computer_use':False,'credential':'existing app vault; never included in report','fixture':str(fixture)}
    try:
        reference=request('/api/uploads',fixture.read_bytes(),'image/png')
        message = ('请严格按照参考图片中的全部标注新建零件，包括外轮廓台阶、斜边及全部通孔。尺寸只从图中读取，不猜测，不省略特征。保存SLDPRT和STEP，检查实际外形、孔径、孔位、体积及草图约束并导出预览。'
            if complex_fixture else '请按图创建L形拉伸实体。总宽40毫米，总高30毫米，两条臂的宽度均为10毫米，沿轮廓平面法线拉伸8毫米。不加孔、圆角或其他特征。保存SLDPRT、导出STEP，检查体积应为4800立方毫米，生成预览。')
        job=request('/api/jobs',json.dumps({'message':message,
            'reference_ids':[reference['id']],'reference_mode':'dimensions'}).encode())
        previous=None;deadline=time.monotonic()+480
        while manager.active and time.monotonic()<deadline:
            state=manager.get(job['id'])
            if state['phase']!=previous:
                print('LIVE_REFERENCE_PHASE '+state['phase'],flush=True);previous=state['phase']
            time.sleep(1)
        state=manager.get(job['id']);report.update(status=state['phase'],job=state)
        if manager.active:raise RuntimeError('Live acceptance timed out; check active job before retry')
        volumes=[r['result'] for r in manager.jobs[job['id']].tool_results if r['tool']=='solidworks_build_reference']
        report['reference_build']=volumes
        print(json.dumps({'status':state['phase'],'summary':state['summary'],'report':str(output/'acceptance.json')},ensure_ascii=False),flush=True)
    finally:
        (output/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not manager.active:
            server.shutdown();server.server_close();manager.pool.shutdown()


if __name__=='__main__':main()
