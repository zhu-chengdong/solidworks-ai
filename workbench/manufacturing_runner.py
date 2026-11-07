"""Natural-language drawing planning, bounded native execution and visual review."""
import base64,json
from pathlib import Path
from .engine import (Agent,FunctionTool,Runner,Plan,Review,ModelOutputLimit,
    ModelBehaviorError,ProgressHooks,UserFacingError,mcp_data,failed_result,model_settings,
    call_native,set_function_tool_failure_error_function,RUN_CONFIG)
from .model_routing import tool_profile
from engineering.manufacturing_spec import ManufacturingRequest,STAGES


class DrawingPlan(Plan):
    drawing:ManufacturingRequest|None=None


async def run_manufacturing(engine,job):
    if len(job.cad_inputs)!=1 or job.references or job.drawing_inputs:
        job.finish('clarify','请添加一个 SLDPRT 零件文件，再说明工程图要求。本模块从该零件生成工程图。')
        return
    settings=engine.settings.read()
    from .magpie import route_profiles
    profiles=route_profiles(engine.settings,job)
    planner,executor=profiles or (engine.settings.role('planner',settings),engine.settings.role('executor',settings))
    executor=tool_profile(executor)
    if not planner.get('vision',planner['provider']=='openai'):
        job.finish('clarify','制造工程图需要复核真实 PDF 预览。请在设置中为规划与复核选择支持图片的模型，再运行本任务。')
        return
    source=job.cad_inputs[0];source_path=(job.output_dir/source['file']).resolve()
    job.set_phase('planning','读取实际零件并规划制造工程图')
    async with engine.session_factory() as session:
        inspected=await call_native(job,session,'solidworks_inspect_input_part',{'params':{'input_path':str(source_path),'sha256':source['sha256']}})
        facts=mcp_data(inspected);job.evidence('solidworks_inspect_input_part',facts)
        if failed_result(inspected,facts):raise UserFacingError('原生零件读取未通过，尚未创建工程图。')
        if facts.get('body_count')!=1:raise UserFacingError('本批制造工程图只验收单实体零件。')
        prompt=('根据用户需求与实际原生检查结果规划工程图。已有几何由原生API测量，不能猜尺寸或改写零件。'
            '当前可执行范围：单SLDPRT单实体、A3横向、第一角主/俯/左三视图（左视在主视右侧）、'
            '整体XYZ关联尺寸、最高+Z平面圆孔位置和真实孔标注、一个水平或垂直的直线全剖、原生SLDDRW与PDF。'
            '比例未指定时scale=null由测量尺寸适配；剖切位置未指定时at_mm=null从实际孔位或中心选取。'
            'section.axis=x指在主视模型XY平面沿X方向的剖切线，at_mm是Y坐标；axis=y反之。'
            '未给定公差、GD&T、材料或工艺不得编造。用户只要求标称图纸时不必追问这些未请求项。'
            '请求超出该范围（右视替代左视、局部/阶梯剖视、多页、侧孔标注、指定公差/GD&T）则supported=false并给出具体说明。'
            'action=create表示新建工程图，原零件不修改。只输出DrawingPlan。\n'
            +json.dumps({'用户要求':job.requests,'源零件名称':source['name'],'实际几何':facts},ensure_ascii=False))
        current=dict(planner)
        for attempt in range(2):
            try:
                plan=await engine.structured(current,prompt,DrawingPlan,job)
                break
            except (ModelOutputLimit,ModelBehaviorError) as exc:
                if attempt:raise
                if isinstance(exc,ModelOutputLimit):current['token_budget']=min(128000,current.get('token_budget',16384)*2)
                prompt+='\n前次方案未完成或不符合结构。保留原始需求，重新给出有效方案；不得在无方案时写入CAD。'
                job.event('planning_retry','方案尚未有效，进行一次有界修正，尚未写入CAD。')
        job.set_plan(plan.model_dump())
        if plan.needs_clarification or not plan.supported or plan.drawing is None:
            job.finish('clarify',plan.summary+'\n'+'\n'.join(plan.questions));return
        if plan.action!='create':raise UserFacingError('工程图任务必须创建独立工程图，不修改原零件。')
        spec_path=job.output_dir/'manufacturing-spec.json'
        spec_path.write_text(json.dumps({'source':{'path':str(source_path),'sha256':source['sha256']},'request':plan.drawing.model_dump()},ensure_ascii=False,indent=2),encoding='utf8')
        job.set_phase('executing','执行模型正在创建原生制造工程图')
        invoked=False
        async def invoke(_context,arguments):
            nonlocal invoked
            if invoked:raise UserFacingError('本次工程图已经启动，不能重复执行写入。')
            if json.loads(arguments)!={}:raise UserFacingError('工程图路径和阶段由本任务确定，执行模型不能改变。')
            invoked=True
            for index,label in enumerate(STAGES):
                job.check_stop();job.event('tool_start',label,tool='solidworks_manufacturing_drawing')
                result=await call_native(job,session,'solidworks_manufacturing_drawing',{'params':{'spec_path':str(spec_path),'stage':index}})
                data=mcp_data(result);job.evidence('solidworks_manufacturing_drawing',data)
                if failed_result(result,data):raise UserFacingError(label+'未通过，阶段文件已保留。'+str(data.get('message','')))
                if data.get('completed_stages')!=index+1:raise UserFacingError('工程图阶段回读不一致，已停止后续写入。')
                job.owns_document=True;job.event('tool_done',label+'完成',tool='solidworks_manufacturing_drawing')
            proof=data.get('verification') or {}
            if not data.get('complete') or proof.get('status')!='passed' or not data.get('package_verified'):
                raise UserFacingError('工程图尚未完成原生和PDF交付核验。')
            return json.dumps({'status':'passed','complete':True,'save_reopen_verified':True,
                'projection':proof['projection'],'views':list(proof['standard_views']),
                'dimensions':[{k:d[k] for k in ('id','value_m','is_hole_callout')} for d in proof['dimensions']],
                'section_verified':proof['section'] is not None,'pdf_review_passed':proof['pdf_review']['passed'],
                'source_preserved':True,'package':Path(data['package']).name,'nominal_geometry_only':True},ensure_ascii=False)
        tool=FunctionTool(name='solidworks_manufacturing_drawing',description='一次调用，按已确认方案原生创建三视图、关联尺寸、孔标注、剖视、SLDDRW和PDF，并保存重开核验。禁止重复调用。',
            params_json_schema={'type':'object','properties':{},'required':[],'additionalProperties':False},on_invoke_tool=invoke,strict_json_schema=True)
        tool=set_function_tool_failure_error_function(tool,None)
        async with engine.model_factory({**executor,'_job':job,'_role':'executor'}) as model:
            agent=Agent(name='原生工程图执行',model=model,tools=[tool],model_settings=model_settings(executor,'executor'),
                instructions='必须且仅一次调用提供的原生工具，之后依据实际返回简洁报告。不能使用鼠标键盘或任意代码。标称图纸核验不等于制造或公差认证。\n'+json.dumps(plan.model_dump(),ensure_ascii=False))
            completed=await Runner.run(agent,'执行已经明确的工程图方案。',max_turns=3,run_config=RUN_CONFIG,hooks=ProgressHooks(job))
        if not invoked:raise UserFacingError('执行模型没有完成实际出图调用。')
        job.set_phase('checking','Sol正在复核原生工程图和PDF预览')
        proof=json.loads((job.output_dir/'manufacturing-acceptance.json').read_text(encoding='utf8'))
        preview=job.output_dir/proof['preview']
        if not preview.is_relative_to(job.output_dir) or not preview.is_file():raise UserFacingError('工程图PDF预览缺失。')
        job.review_status={'state':'reviewing','rounds':1,'repair_count':0}
        review_input=[{'role':'user','content':[
            {'type':'input_text','text':'复核本次真实原生工程图PDF渲染。核对主/俯/左第一角布局、尺寸与孔标注可读、剖切线/箭头/剖面线、无裁切或重叠。只核对明确范围；没有请求的公差和工艺不应被编造或当作自动核验已通过。\n'+json.dumps({'用户要求':job.requests,'方案':plan.model_dump(),'原生和PDF实际证据':proof},ensure_ascii=False)},
            {'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(preview.read_bytes()).decode('ascii'),'detail':'high'}]}]
        review=await engine.structured(planner,review_input,Review,job)
        # A contradictory "passed" response must not hide reported layout defects.
        review.passed=review.passed and not review.issues and not review.preview_issues
        (job.output_dir/'manufacturing-review.json').write_text(json.dumps(review.model_dump(),ensure_ascii=False,indent=2),encoding='utf8')
        job.review_status.update(state='passed' if review.passed else 'unresolved',last_report='manufacturing-review.json')
        if not review.passed:job.review_reasons.update(review.issues or ['工程图视觉复核尚未通过'])
        job.review_reasons.add('标称图纸已核验；公差、工艺与制造用途仍请本人确认')
        job.collect_artifacts()
        job.finish('review_required',str(completed.final_output)+'\n\n'+review.summary+'\n\n需要复核：\n'+'\n'.join(sorted(job.review_reasons)))
