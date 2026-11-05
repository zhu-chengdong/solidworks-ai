"""Bounded review -> view-only execution -> fresh review, preserving every round."""
import base64,hashlib,json,shutil
from pathlib import Path
from agents import Agent,FunctionTool,Runner
from engineering.previews import active_preview_entries,digest
from .settings import UserFacingError,redact

def clone_for_preview_review(source,root):
    from .jobs import Job,ACTIVE
    from .engine import EngineeringPlan
    root=Path(root).resolve();directory=Path(source['output_dir']).resolve()
    if source.get('phase') in ACTIVE or directory.parent!=root:raise UserFacingError('只能复核本机已结束的建模任务。')
    plan=EngineeringPlan.model_validate(source.get('plan'))
    if plan.design is None:raise UserFacingError('此任务没有可复核的结构化零件或装配方案。')
    record=json.loads((directory/'design-acceptance.json').read_text(encoding='utf-8'))
    if not record['verification'].get('passed'):raise UserFacingError('原生几何尚未通过，不能只修正预览。')
    if not Path(record['active_path']).resolve().is_relative_to(directory):raise UserFacingError('请从原建模任务发起重新复核。')
    members=[];protected={}
    for name,sha in record['package_hashes'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory) or digest(path)!=sha:raise UserFacingError('原任务文件或哈希已改变。')
        if name=='preview-repair-attempt.json':raise UserFacingError('原交付清单包含任务控制文件。')
        members.append((name,path))
        if path.suffix.lower() in {'.sldasm','.sldprt','.step','.stp'}:protected[str(path)]=sha
    package=Path(record['package']).resolve()
    if package.parent!=directory or digest(package)!=record['package_sha256']:raise UserFacingError('原交付包校验失败。')
    # Validate first so a damaged source cannot leave a phantom queued task.
    job=Job('重新复核并按需修正预览，保持模型不变。',root,{'requests':source['requests'],'source_job_id':source['id']})
    job.set_plan(plan.model_dump())
    for name,path in members:
        target=job.output_dir/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    protected[str(package)]=digest(package);shutil.copy2(package,job.output_dir/package.name)
    record['package']=str(job.output_dir/package.name)
    (job.output_dir/'design-acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    (job.output_dir/'preview-source.json').write_text(json.dumps({'source_job_id':source['id'],'active_path':record['active_path'],'files':protected},ensure_ascii=False,indent=2),encoding='utf-8')
    job.owns_document=True;job.review_status={'mode':'preview_only'}
    job.evidence('solidworks_execute_design',{'verification':record['verification'],'parts':record['parts'],'package':record['package'],'source_job_id':source['id'],'reused_existing_geometry':True})
    job.collect_artifacts();return job

async def execute_preview_repair(engine,job,session,profile,issues):
    from .engine import model_settings,ProgressHooks,RUN_CONFIG,mcp_data,failed_result
    from .native_wait import call_native
    called=False
    async def invoke(context,raw):
        nonlocal called
        job.check_stop()
        if called or json.loads(raw or '{}')!={}:raise UserFacingError('预览仅允许一次受限修正，不能改变任务或模型。')
        called=True;job.event('preview_repair','正在通过原生 API 重出三视图',issues=issues)
        result=await call_native(job,session,'solidworks_repair_design_previews',{'params':{'output_dir':str(job.output_dir)}})
        data=mcp_data(result);job.evidence('solidworks_repair_design_previews',data)
        if failed_result(result,data) or data.get('native_files_unchanged') is not True or data.get('package_verified') is not True:raise UserFacingError('预览修正或模型保护检查未通过。')
        job.collect_artifacts();job.check_stop()
        return json.dumps(data,ensure_ascii=False)
    tool=FunctionTool(name='solidworks_repair_design_previews',description='仅重出当前任务已通过几何检查的原生预览和依赖包。调用一次，不改变几何或配合。',
        params_json_schema={'type':'object','properties':{},'required':[],'additionalProperties':False},on_invoke_tool=invoke,strict_json_schema=True)
    from agents.tool import set_function_tool_failure_error_function
    tool=set_function_tool_failure_error_function(tool,None)
    async with engine.model_factory({**profile,'_job':job,'_role':'executor'}) as model:
        agent=Agent(name='修正三视图',model=model,instructions='复核发现预览问题：'+json.dumps(issues,ensure_ascii=False)+'。必须且仅一次调用提供的原生修正工具，然后简述实际结果。不得改动模型或假称已再次复核。',
            tools=[tool],model_settings=model_settings(profile,'executor'))
        await Runner.run(agent,'修正当前任务的预览。',max_turns=3,run_config=RUN_CONFIG,hooks=ProgressHooks(job))
    if not called:raise UserFacingError('执行模型没有调用原生预览修正工具。')

async def review_delivery(engine,job,session,plan,planner,executor,summary):
    from .engine import Review,JobStopped,image_input,inside
    planner = getattr(job, '_reviewer_profile', planner)
    mode=job.review_status.get('mode');job.review_status={'mode':mode,'state':'reviewing','rounds':0,'repair_count':0}
    previous_review=None
    for index in range(2):
        job.check_stop();job.collect_artifacts()
        previews=[a for a in job.artifacts if a['preview']]
        try:manifest=active_preview_entries(job.output_dir);manifest_error=None
        except (ValueError,KeyError,OSError) as exc:manifest=[];manifest_error=type(exc).__name__
        legacy=(job.output_dir/'design-acceptance.json').exists() and manifest is None
        text=('你只复核实际结果，不操作。对照原需求、原生回读、最新预览及文件判断是否满足。'
            '任务模式preview_only表示复核已完成任务的既有模型，原需求仅用于检查模型和交付，不要求本轮再从零创建。'
            '预览的朝向、名称标识、空白或缺图问题填preview_issues（orientation、labels、blank、missing）；其他问题只填issues。'
            '若passed=true则preview_issues必须为空。不要把材料/承载未指定当作静态演示几何失败。'
            '装配已有GetExtremePoint尺寸、真实配合、完全约束、干涉、重开、STEP重导入及打包哈希，不要求重复调用同名工具。'
            '预览按固定底座局部X为左右、Z为高度的统一相机基准，前视看+Y、右视看-X、俯视看-Z；'
            '该基准通过实测组件矩阵转换到世界坐标。世界XYZ置换不等于实体放错位置；请依据清单中的相机回读及图像核查。'
            '当前有清单时，只复核清单指定的最新四图，旧预览和早期工具输出只作历史。'
            '仅BMP转PNG属于格式转换，不会改变相机或几何。最终依据当前交付包和文件清单判断。\n'
            +json.dumps({'任务模式':mode,'原需求':job.previous_context.get('requests') or job.requests,'方案':plan.model_dump(),
                '原生结果':job.tool_results,'当前文件':job.artifacts,'当前视图清单':manifest,'清单检查错误':manifest_error,'上一轮全部复核问题（逐项重新检查，不得仅因重出图片跳过其他问题）':previous_review,'review_round':index+1},ensure_ascii=False))
        review_input=text
        if previews and planner.get('vision',planner['provider']=='openai'):
            chosen=sorted(previews,key=lambda a:(a.get('view_id')!='isometric','isometric' not in a['name']))[:4]
            content=image_input(job,text)[0]['content']
            for item in chosen:
                file=job.output_dir/item['name']
                if inside(file,job.output_dir) and file.stat().st_size<=4_000_000:
                    content.extend([{'type':'input_text','text':'当前实际预览：'+str(item.get('view_label') or item['name'])+' '+item['name']},
                        {'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(file.read_bytes()).decode('ascii'),'detail':'high'}])
            review_input=[{'role':'user','content':content}]
        elif previews:job.review_reasons.add('当前供应商仅完成文本复核，预览图请本人检查')
        job.event('review_round','正在'+('再次' if index else '')+'复核实际模型与三视图',round=index+1)
        review=await engine.structured(planner,review_input,Review,job)
        if review.passed and review.preview_issues:raise UserFacingError('复核结论与预览问题标识矛盾，已停止自动修正。')
        report={'round':index+1,**review.model_dump(),'preview_files':[a['name'] for a in previews],
            'preview_sha256':{a['name']:digest(job.output_dir/a['name']) for a in previews},'manifest_error':manifest_error,'legacy_manifest_missing':legacy}
        reports=job.output_dir/'reviews';reports.mkdir(exist_ok=True)
        (reports/f'round-{index+1}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        previous_review=report
        job.review_status.update(rounds=index+1,last_report=f'reviews/round-{index+1}.json')
        job.event('review_result','三视图复核'+('通过' if review.passed else '发现问题'),round=index+1,passed=review.passed,preview_issues=review.preview_issues)
        issues=list(review.preview_issues)
        if legacy or manifest_error:issues.append('missing' if legacy else 'labels')
        if issues and index==0:
            record=job.output_dir/'design-acceptance.json'
            if record.exists() and json.loads(record.read_text(encoding='utf-8'))['verification'].get('passed'):
                job.review_status.update(state='repairing',repair_count=1)
                await execute_preview_repair(engine,job,session,executor,issues)
                job.review_status['state']='reviewing';continue
        if not review.passed or issues:job.review_reasons.update(review.issues or [review.summary])
        job.review_status['state']='passed' if review.passed and not issues else 'unresolved'
        prefix=('三视图已自动修正，并经再次复核通过。\n' if index and job.review_status['state']=='passed' else '')
        job.collect_artifacts();return prefix+review.summary+'\n\n'+summary
    raise UserFacingError('预览自动修正达到上限，保留未通过结果。')
