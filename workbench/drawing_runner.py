"""No-token vector route, sharing the workbench queue, MCP STA and artifacts."""
import hashlib,json
from pathlib import Path
from drawing2cad.parser import DrawingError,inspect_dxf,options,select_spec,preview
from .native_wait import call_native


async def run_drawing(engine,job):
    from .engine import mcp_data,failed_result
    from .settings import UserFacingError
    if len(job.drawing_inputs)!=1 or job.references or job.cad_inputs:raise UserFacingError('精确图纸建模请单独上传一份DXF/DWG；图片或已有零件请另建任务。')
    item=job.drawing_inputs[0];source=(job.output_dir/item['file']).resolve()
    if not source.is_relative_to((job.output_dir/'inputs'/'drawings').resolve()) or hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:raise UserFacingError('任务图纸校验失败。')
    job.routing={'mode':'local_vector','model_calls':0,'estimated_cost_usd':0,'reason':'直接读取精确图纸坐标，通过原生API创建参数化零件'}
    job.set_phase('planning','读取二维图纸几何与单位')
    try:
        opts=options(job.requests)
        if item['extension']=='.dwg':
            target=job.output_dir/'drawing-converted.dxf'
            if not target.exists():
                job.event('tool_start','通过SolidWorks原生接口转换DWG，不修改原图')
                async with engine.session_factory() as session:
                    result=await call_native(job,session,'solidworks_convert_drawing',{'params':{'input_path':str(source),'sha256':item['sha256'],'output_path':str(target)}})
                    data=mcp_data(result);job.evidence('solidworks_convert_drawing',data)
                    if failed_result(result,data):raise UserFacingError('DWG原生转换未通过，请检查SolidWorks提示或导出DXF后重试。')
            record=json.loads(target.with_suffix('.conversion.json').read_text(encoding='utf-8'))
            if record['source_sha256']!=item['sha256'] or hashlib.sha256(target.read_bytes()).hexdigest()!=record['converted_sha256']:raise UserFacingError('转换图纸校验失败。')
            source=target
        job.check_stop()
        inspection=inspect_dxf(source,opts['unit_override'],advanced=opts.get('advanced',False))
        (job.output_dir/'drawing-inspection.json').write_text(json.dumps(inspection,ensure_ascii=False,indent=2),encoding='utf-8')
        preview(inspection,job.output_dir/'drawing-contours.png')
        spec,question=select_spec(inspection,opts)
        if question:
            job.collect_artifacts();job.finish('clarify',question);return
        if spec.get('kind'):
            summary=('按三个正交轮廓重建原生实体' if spec['kind'] in {'orthographic','orthographic_analytic'} else '按图纸外轮廓建模')+f"，尺寸{'×'.join(f'{v:g}' for v in spec['size_mm'])}毫米，读取{len(spec['holes'])}个孔标注并按各自方向与深度建孔。"
            geometry={'size_mm':spec['size_mm'],'holes':spec['holes'],'views':spec['views'],'assumptions':spec['assumptions']}
        else:
            summary=f"使用视图{spec['id']}，沿原图XY轮廓拉伸{spec['thickness_mm']:g}毫米，内轮廓全部贯穿。"
            geometry={'area_mm2':spec['area_mm2'],'thickness_mm':spec['thickness_mm'],'view_id':spec['id']}
        job.set_plan({'summary':summary,'action':'create','needs_clarification':False,'supported':True,'source':'exact_vector','steps':['识别轮廓、视图、尺寸和孔标注','建立尺寸约束草图和原生特征','保存重开，回读孔深与几何','导出STEP、四视图及交付包'],'geometry':geometry})
        request={'source_file':item['file'],'source_sha256':item['sha256'],'options':opts}
        (job.output_dir/'drawing-spec.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
        job.check_stop();job.set_phase('executing','按精确轮廓建立原生尺寸驱动零件');job.owns_document=True
        async with engine.session_factory() as session:
            result=await call_native(job,session,'solidworks_build_drawing',{'params':{'spec_path':str(job.output_dir/'drawing-spec.json')}})
            data=mcp_data(result);job.evidence('solidworks_build_drawing',data)
            if failed_result(result,data) or data.get('success') is not True:raise UserFacingError('图纸建模未通过原生验收，保留已生成证据，请查看检查结果。')
        job.check_stop();job.collect_artifacts()
        geometry=data['saved_reopened_geometry'];size=geometry['exact_bounds']['size_mm']
        job.finish('completed',f"已从{item['name']}建立可编辑原生零件，尺寸约{size[0]:g}×{size[1]:g}×{size[2]:g}毫米。保存重开后的体积、尺寸、草图约束和STEP实体数量检查通过。已附原生文件、STEP、四视图及交付包。API Token消耗为0。")
    except DrawingError as exc:
        job.collect_artifacts();job.finish('clarify',str(exc))
