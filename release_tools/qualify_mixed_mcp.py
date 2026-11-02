"""Run the validated mixed assembly through a distributed native MCP executable."""
import asyncio,hashlib,json,os,sys,time,uuid,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


async def qualify(executable,source):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client,StdioServerParameters
    from engineering.spec import DesignSpec
    from workbench.jobs import Job
    from workbench.settings import ARTIFACT_ROOT
    from workbench.cad_inputs import pin_cad_inputs
    from workbench.engine import mcp_data,failed_result
    from workbench.native_wait import call_native
    original=json.loads((source/'design-acceptance.json').read_text(encoding='utf-8'))
    plan=DesignSpec.model_validate_json((source/'design-spec.json').read_text(encoding='utf-8'))
    job=Job('支架、轴与孔板：7组件原生MCP验收',ARTIFACT_ROOT);hashes={};inputs=[]
    for part in plan.parts:
        file=Path(original['parts'][part.id]['path']);raw=file.read_bytes();digest=hashlib.sha256(raw).hexdigest();hashes[str(file)]=digest
        asset=uuid.uuid4().hex;inputs.append((file,{'id':asset,'name':part.id+'.SLDPRT','sha256':digest,'size':len(raw)}))
        part.source_id=asset;part.shape='existing';part.holes=[];part.profile=None
    # Existing-part copies keep the source geometry and colors. Suppress unused
    # recipe dimensions so this qualification has no hidden geometry writes.
    for part in plan.parts:
        for key in ('length_mm','width_mm','height_mm','thickness_mm','diameter_mm','wall_mm'):setattr(part,key,None)
    plan=DesignSpec.model_validate(plan.model_dump());pin_cad_inputs(job,inputs)
    spec=job.output_dir/'design-spec.json';spec.write_text(plan.model_dump_json(indent=2),encoding='utf-8')
    job.set_plan({'summary':'按预先核实的参数方案测试原生MCP，不调用模型API。','action':'create','design':plan.model_dump(),'steps':[s['label'] for s in plan.stages()]})
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('API_KEY','ACCESS_TOKEN','SECRET')) and k.upper() not in {'PYTHONHOME','PYTHONPATH'}}
    windows=Path(os.environ.get('WINDIR',r'C:\Windows'));env['PATH']=os.pathsep.join(map(str,[windows/'System32',windows]))
    env['SOLIDWORKS_AI_DATA_HOME']=str(ROOT);env['PYTHONUTF8']='1'
    params=StdioServerParameters(command=str(executable),args=[],cwd=str(executable.parent),env=env)
    try:
        job.set_phase('executing','正在执行7组件原生验收')
        with (job.output_dir/'mcp-native.log').open('w',encoding='utf-8') as log:
            async with stdio_client(params,errlog=log) as streams:
                async with ClientSession(*streams,read_timeout_seconds=None) as session:
                    await session.initialize()
                    tools=await session.list_tools();assert any(t.name=='solidworks_execute_design' for t in tools.tools)
                    for index,stage in enumerate(plan.stages()):
                        job.event('tool_start',stage['label'],tool='solidworks_execute_design')
                        result=await call_native(job,session,'solidworks_execute_design',{'params':{'spec_path':str(spec),'output_dir':str(job.output_dir),'stage':index}})
                        data=mcp_data(result);job.evidence('solidworks_execute_design',data);job.owns_document=True
                        print(json.dumps({'stage':index,'label':stage['label'],'status':data.get('status')},ensure_ascii=False),flush=True)
                        if failed_result(result,data):raise RuntimeError(data.get('message','Native stage failed; no replay'))
        native=json.loads((job.output_dir/'design-acceptance.json').read_text(encoding='utf-8'))
        assert native['status']=='passed' and native['verification']['component_count']==7
        assert native['verification']['mate_readback']['passed'] and native['verification']['interference']['interference_count']==0
        assert native['verification']['step_reimport']['reimported_body_count']==7
        assert all(c['constrained_status']==3 and c['pose_verified'] for c in native['verification']['components'])
        for file,digest in hashes.items():assert hashlib.sha256(Path(file).read_bytes()).hexdigest()==digest
        with zipfile.ZipFile(native['package']) as archive:
            for name,digest in native['package_hashes'].items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
        job.collect_artifacts();job.finish('review_required','已通过7组件、5种零件和15个真实配合的原生验收。两个支架采用相反方向旋转；所有实例完全约束，零干涉，保存重开和7实体STEP重导入通过。全部输入原件哈希保持。制造、承载及公差请本人复核。此任务仅调用原生MCP，没有调用模型API。')
        receipt={'status':'passed','exe':str(executable),'job_id':job.id,'output_dir':str(job.output_dir),'native_api_only':True,'model_api_called':False,'computer_use':False,'external_python_paths_removed':True,'original_files_unchanged':True,'native':native}
        (job.output_dir/'packaged-mcp-acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PACKAGED_MIXED_PASS '+str(job.output_dir),flush=True)
    except BaseException:
        job.collect_artifacts();job.finish('review_required','原生验收尚未通过，现场已保留，没有重放失败的写入。');raise


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(qualify(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve()))
