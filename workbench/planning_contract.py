"""Compact parameter contract for a new task; detailed source edits retain full context."""
import json
def new_task_prompt(requests,context):
    from engineering.spec import PartSpec,skill_context
    c=skill_context()
    contract={
      'units':c['units'],'recipes':c['part_recipes'],
      'part_fields':list(PartSpec.model_fields),
      'workflow':'只输出结构化设计参数、必要问题和简明验收项。原生编译器负责草图驱动约束、拓扑选择、真实配合、保存重开、STEP回导和四视图；不要编写代码或推演低层调用，也不要手算圆弧端点、面积、体积和质量。此时尚未执行，不能声称实测通过。',
      'completeness':'缺少关键设计尺寸、接口、孔类型或配合关系时先澄清，design=null。不得猜造关键输入或默默省略特征。未要求的特征/材料用空值或空列表。Schema无法完整表达的功能supported=false。只支持本机SolidWorks原生API，禁止鼠标键盘、窗口自动化和任意脚本；所有新文件另存，不能覆盖或删除原稿。',
      'assembly':c['assembly'],'plane_mate_math':c['plane_mate_math'],
      'native_features':'edge_treatments为常半径圆角/距离角度倒角；standard_holes为ISO孔向导，size为螺钉公称规格而非钻孔直径，depth_mm=null才是贯穿。真实螺纹只支持局部+Z粗牙ISO；新内螺纹用tapped+modeled并明确thread_depth_mm；编译器计算载体直径，不重复另造孔。hole_patterns种子为本part.standard_holes的0起索引，数量包含种子，圆周阵列须有唯一真实Z圆柱轴，镜像限XZ/YZ；不能用独立复制孔冒充关联阵列。planar_cuts仅最高+Z平面直长圆槽和简单多边形，槽length_mm是含两端半圆的总长，depth_mm=null贯穿，其余为小于料厚的平底盲切；不允许与已有空腔相交或越边。驱动草图零Fix由编译器负责。',
      'delivery':c['native_design_workflow']['built_in_delivery'],'preview_views':c['native_design_workflow']['preview_views'],
      'unqualified':c['not_yet_qualified']}
    if 'material' in PartSpec.model_fields:
        contract['materials']='material可空以保留已有赋值；标准grade从真实安装库读取名称密度；custom_density须用户明确label及density_kg_m3且单配置。未知材料不能当已知质量，STEP本批只核验几何。'
    return '把用户需求转成SolidWorks设计方案；仅返回要求的JSON。\n'+json.dumps({'用户输入记录':requests,'当前SolidWorks':context,'原生参数契约':contract},ensure_ascii=False)
