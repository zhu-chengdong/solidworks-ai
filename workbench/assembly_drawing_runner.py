"""Natural-language flat-assembly drawings through bounded native API calls."""
import base64,json
from pathlib import Path
from .engine import (Agent,FunctionTool,Runner,Plan,Review,ModelOutputLimit,ModelBehaviorError,
    ProgressHooks,UserFacingError,mcp_data,failed_result,model_settings,call_native,
    set_function_tool_failure_error_function,RUN_CONFIG)
from .model_routing import tool_profile
from engineering.assembly_drawing_spec import AssemblyDrawingRequest,STAGES

class AssemblyDrawingPlan(Plan):
    drawing:AssemblyDrawingRequest|None=None

async def run_assembly_drawing(engine,job):
    if len(job.cad_inputs)!=1 or job.cad_inputs[0].get('kind')!='assembly' or job.references or job.drawing_inputs:
        job.finish('clarify','请在装配工程图中添加一个包含SLDASM及全部SLDPRT依赖的ZIP。');return
    settings=engine.settings.read()
    from .magpie import route_profiles
    profiles=route_profiles(engine.settings,job)
    planner,executor=profiles or (engine.settings.role('planner',settings),engine.settings.role('executor',settings));executor=tool_profile(executor)
    if not planner.get('vision',planner['provider']=='openai'):
        job.finish('clarify','装配工程图需要复核真实PDF预览，请为规划复核配置支持图片的模型。');return
    source=job.cad_inputs[0]
    prompt=('依据用户要求规划原生装配工程图，只输出AssemblyDrawingPlan。当前支持：一个依赖完整的扁平装配、至多12种零件/24实例、A3横向第一角、等轴测/前视/俯视、原生仅零件BOM、每实例一个原生关联序号气泡、SLDDRW及PDF和依赖包。'
        '此处只有文件元数据，实际组件、数量与关联全部由原生执行器核对，不得猜尺寸或数量。action=create，生成独立副本，不修改原文件。未指定比例使用null。'
        '不支持嵌套装配、爆炸图、装配剖视、多页、指定公差或配合编辑；如要求这些则supported=false并明确说明。不得编造材料、公差或制造结论。\n'
        +json.dumps({'用户要求':job.requests,'上传文件':source['name'],'原生文档名称':[d['name'] for d in source['documents']]},ensure_ascii=False))
    job.set_phase('planning','规划装配工程图、BOM和关联气泡');current=dict(planner)
    for attempt in range(2):
        try:plan=await engine.structured(current,prompt,AssemblyDrawingPlan,job);break
        except (ModelOutputLimit,ModelBehaviorError) as exc:
            if attempt:raise
            if isinstance(exc,ModelOutputLimit):current['token_budget']=min(128000,current.get('token_budget',16384)*2)
            prompt+='\n前次结构未完成，保留原始需求，重新输出完整有效方案。尚未写入CAD。'
    job.set_plan(plan.model_dump())
    if not plan.supported or plan.needs_clarification or plan.drawing is None:
        job.finish('clarify',plan.summary+'\n'+'\n'.join(plan.questions));return
    if plan.action!='create':raise UserFacingError('装配工程图只创建独立图纸，不修改原装配。')
    spec_path=job.output_dir/'assembly-drawing-spec.json'
    spec={'source':{'path':str(job.output_dir/source['assembly_file']),
          'documents':[{'path':str(job.output_dir/d['file']),'sha256':d['sha256']} for d in source['documents']]},'request':plan.drawing.model_dump()}
    spec_path.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf8')
    async with engine.session_factory() as session:
        invoked=False
        async def invoke(_context,arguments):
            nonlocal invoked
            if invoked or json.loads(arguments)!={}:raise UserFacingError('装配工程图已启动或参数被更改，不能重复写入。')
            invoked=True
            for index,label in enumerate(STAGES):
                job.check_stop();job.event('tool_start',label,tool='solidworks_assembly_drawing')
                result=await call_native(job,session,'solidworks_assembly_drawing',{'params':{'spec_path':str(spec_path),'stage':index}})
                data=mcp_data(result);job.evidence('solidworks_assembly_drawing',data)
                if failed_result(result,data) or data.get('completed_stages')!=index+1:raise UserFacingError(label+'未通过，已保留本轮证据。')
                job.owns_document=True;job.event('tool_done',label+'完成',tool='solidworks_assembly_drawing')
            proof=data.get('verification') or {}
            if not data.get('complete') or not data.get('package_verified') or not proof.get('passed'):raise UserFacingError('装配工程图交付验收尚未通过。')
            return json.dumps({'status':'passed','component_count':proof['component_count'],'bom_rows':len(proof['bom']['rows']),
                'associated_balloons':len(proof['balloons']),'saved_reopened':True,'pdf_verified':True,'source_preserved':True,'package':Path(data['package']).name},ensure_ascii=False)
        tool=FunctionTool(name='solidworks_assembly_drawing',description='按已确认方案一次执行原生装配工程图、真实BOM和每组件关联气泡，保存重开核验、导出PDF和完整依赖包。禁止重复调用。',
            params_json_schema={'type':'object','properties':{},'required':[],'additionalProperties':False},on_invoke_tool=invoke,strict_json_schema=True)
        tool=set_function_tool_failure_error_function(tool,None)
        job.set_phase('executing','执行模型正在生成原生装配工程图')
        async with engine.model_factory({**executor,'_job':job,'_role':'executor'}) as model:
            agent=Agent(name='原生装配出图执行',model=model,tools=[tool],model_settings=model_settings(executor,'executor'),
                instructions='必须且仅一次调用工具，工具参数固定为空。之后只依据实际结果简洁汇报。禁止任意代码、鼠标键盘和重复调用。\n'+json.dumps(plan.model_dump(),ensure_ascii=False))
            result=await Runner.run(agent,'执行已确认的装配工程图方案。',max_turns=3,run_config=RUN_CONFIG,hooks=ProgressHooks(job))
        if not invoked:raise UserFacingError('执行模型未完成原生装配出图调用。')
    proof=json.loads((job.output_dir/'assembly-drawing-acceptance.json').read_text(encoding='utf8'));preview=job.output_dir/proof['preview']
    if not preview.is_relative_to(job.output_dir) or not preview.is_file():raise UserFacingError('实际PDF预览不存在。')
    job.set_phase('checking','复核实际装配工程图PDF与BOM气泡关联');job.review_status={'state':'reviewing','rounds':1,'repair_count':0}
    evidence={k:proof[k] for k in ('component_count','views','bom','balloons','save_reopen_verified','qualification_scope')}
    review=await engine.structured(planner,[{'role':'user','content':[
        {'type':'input_text','text':'复核这张真实原生装配工程图PDF预览。检查BOM可读，数量和序号与原生证据一致，每实例气泡引线清楚，无交叉歧义、遮挡或裁切；视图清楚且标签准确。不要把未请求的公差或爆炸图当作本次通过条件。\n'+json.dumps({'用户要求':job.requests,'实际证据':evidence},ensure_ascii=False)},
        {'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(preview.read_bytes()).decode(),'detail':'high'}]}],Review,job)
    review.passed=review.passed and not review.issues and not review.preview_issues
    (job.output_dir/'assembly-drawing-review.json').write_text(json.dumps(review.model_dump(),ensure_ascii=False,indent=2),encoding='utf8')
    job.review_status.update(state='passed' if review.passed else 'unresolved',last_report='assembly-drawing-review.json')
    if not review.passed:job.review_reasons.update(review.issues or ['装配工程图视觉复核尚未通过'])
    job.review_reasons.add('装配图标称BOM与气泡已核验；制造、公差与装配用途仍请本人确认')
    job.collect_artifacts();job.finish('review_required',str(result.final_output)+'\n\n'+review.summary+'\n\n需要复核：\n'+'\n'.join(sorted(job.review_reasons)))
