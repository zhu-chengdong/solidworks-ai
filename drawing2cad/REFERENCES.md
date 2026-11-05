# 二维图纸到原生参数化零件

核实日期为2026-11-05。本模块是本项目的受限实现，不包含神经网络权重或任意代码执行。

参考项目及采用范围：

- [Drawing2CAD](https://github.com/lllssc/Drawing2CAD)，MIT，核对README提交 `e39777723e83d0d2244d008497e8e1f21c193caa`。参考矢量视图归一化、视图与建模序列分离的思路。其训练/推理环境需要CUDA；本项目未移植其模型、训练数据或推理代码，也不宣称实现其论文的通用重建能力。
- [CAD2Program](https://github.com/manycore-research/CAD2Program)，核对README提交 `b7790a6a39f372cbf6a29bf89c5cac20b20e9012`。公开仓库当前是项目展示网站，未提供可直接集成的完整推理实现。本项目未复制网站代码或素材。
- [ezdxf](https://github.com/mozman/ezdxf)，MIT，Copyright (c) 2020 Manfred Moitzi。[EdgeSmith文档](https://ezdxf.readthedocs.io/en/stable/edgesmith.html)说明精确圆弧与链构建方法；本项目不使用自动补缝来修改制造轮廓。实际依赖版本由发行包DEPENDENCIES.json记录。
- [SolidWorks 2024 IImportDxfDwgData.ImportMethod](https://help.solidworks.com/2024/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IImportDxfDwgData~ImportMethod.html)。DWG只导入Model空间，明确激活Model图纸并暂时设置仅导出当前图纸；结束后恢复导出选项。真实测试发现默认多图纸导出会把图框放入模型空间，因此禁止沿用默认导出选项。
- [pypdfium2](https://github.com/pypdfium2-team/pypdfium2)，PDFium包装。只在本机将1至4页PDF渲染成受限尺寸参考图片。运行库及PDFium版权许可随EXE依赖元数据保留。

0.6.0精确轮廓范围以及0.7.0扩展范围：

- DXF模型空间、DWG的Model空间，平面LINE、ARC、CIRCLE、LWPOLYLINE以及旧式二维POLYLINE。图块支持受限展开，保留变换后的真实几何。
- 等厚拉伸、圆孔及其他闭合内轮廓的贯穿切除。精确圆弧创建为原生圆弧，采样只用于轮廓有效性及二维预览。
- 多个独立外轮廓会先出编号识别图，请用户指定视图；厚度和贯穿意图必须明确。程序不会把三个视图拉伸成三个零件。
- 未声明单位、非毫米图纸未声明厚度单位、尺寸文字覆盖或DIMLFAC与几何冲突、开放/分叉/接触/自交轮廓会停止并询问。标注冲突仅在用户明确“忽略标注”后按坐标继续。
- 保留原图与SHA256，完全定义草图、真实驱动尺寸、零Fix、原生拉伸、保存重开检查、体积/极值尺寸/圆柱面校核、AP214实体计数、四个原生相机视图、带SHA256的ZIP。
- 支持的精确矢量路径不调用模型、不要求API密钥，也不回退到付费API。

0.7.0新增联合三视图和孔深路径：

- 使用FRONT/TOP/RIGHT或主视图/俯视图/右视图标识匹配视图，亦可在对话中指定编号。检查长宽高与投影一致性，支持由直角阶梯轮廓确定的实心棱柱交集，将高度层编译成真实尺寸驱动的合并凸台。未标出的内部空腔不推断。
- 通过LEADER引线关联孔与标注，支持明确的平底盲孔、通孔、通底或盲底圆柱沉孔。孔从俯视图沿Z向创建，深度从各自入口台阶量起。单视图仍支持含精确圆弧的外轮廓。
- 典型标注为`H1 DIA8 BLIND DEPTH12`、`H2 DIA6.6 THRU CBORE DIA13 DEPTH5`、`H3 DIA8 BLIND DEPTH20 CBORE DIA14 DEPTH6`，或相应Ø/深度写法。图纸须注明平底或由用户确认，缺少底形、孔深或视图关联时先询问。
- SolidWorks原生导出可能把LEADER打散。程序只在专用LEADERS/引线图层关联相连线段、圆心和标注，不把这些图形作为外轮廓；已验证的SW_HATCH导出图形作为填充图元忽略。
- 回读实际切除特征的深度和终止方式、圆柱面的精确轴向区间、盲孔平底圆盘、整体验积、极值尺寸，以及三视图外轮廓和内部可见直线与原生B-Rep边的投影覆盖。保存重开后再次执行同样检查，不以请求参数代替验收。
- 工作台可直接下载自产示例DXF，带六个主要尺寸、孔位表、隐藏线及五条孔引线。示例为本项目自行绘制，不属于用户科研CAD。
- 隐藏线也必须关联到已识别孔在对应视图中的投影范围。未知内部轮廓或孔深修改与原隐藏线冲突时，在原生写入前停止并请求剖视/特征说明，不能将它们默认为实心。

0.8.0新增斜面、圆弧三视图与三方向锥形孔路径：

- 三个正交外轮廓定义棱柱交集。TOP精确轮廓先拉伸，再用FRONT/RIGHT轮廓执行原生双向外侧贯穿切除。原始LINE/ARC/CIRCLE是建模输入，采样折线只用于拓扑识别、投影验证和预览。一般组合采用解析截面区间的有界自适应积分核对体积；单轮廓棱柱使用解析面积乘长度。
- 圆弧外轮廓混有内部可见线时，先分析拓扑，再找回完整的原始圆弧。原曲线只有部分属于外边界时要求先在CAD交点处分割，不以采样边替代。
- 孔在TOP沿−Z、FRONT沿+Y、RIGHT沿−X进入。入口必须位于完整平面，贯穿出口也要求完整平面；检查局部材料、底壁与孔段包络。无法确定的相交孔、跨曲面孔及反向/斜向孔不猜测。
- 钻尖盲孔示例为`H1 DIA8 BLIND CYL DEPTH18 POINT118`或`TOTAL DEPTH20 POINT118`，分别表示圆柱段深度和含钻尖总深度。钻尖高度由半径除以半夹角正切计算。沉头示例为`H2 DIA6.6 THRU CSK DIA13 ANGLE90`，需两级同心圆、两级直径与明确夹角，显式深度必须与几何一致。
- 钻尖及沉头以原生旋转切除建立解析圆锥面。保存重开后检查真实旋转角度、圆锥半夹角、端部圆半径与轴向位置，以及原生修剪锥面的顶点最近点；不是把期望参数重新打印成验收结果。圆柱孔区间、终止方式、体积、极值尺寸、完全定义和零Fix仍须通过。
- 曲线三视图复核由实际B-Rep边及位于修剪圆柱面上的切向母线生成投影。验证采样弦差目标0.002毫米，允许的投影Hausdorff距离0.025毫米；每份报告记录数值。这是投影核验容差，不能等同于制造公差，模型本体仍为原生精确几何。
- 一般三视图只能确定外形视觉包络，不能唯一恢复未标出的内部结构。隐藏线必须与已定义的孔投影一致；未解释的内部结构会停止并要求剖视。原生投影不一致的模型不得交付为已通过。

原生API依据包括[FeatureCut4](https://help.solidworks.com/2024/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeatureManager~FeatureCut4.html)、[FeatureRevolve2](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.ifeaturemanager~featurerevolve2.html)、[IEdge.Evaluate2](https://help.solidworks.com/2024/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IEdge~Evaluate2.html)及[ISurface.ConeParams2](https://help.solidworks.com/2024/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.ISurface~ConeParams2.html)。这些接口在本地2024环境中单独验证，不据其他年份的上游能力表宣称兼容。

仍未覆盖任意自由曲面三视图重建、螺纹和装配重建。DWG纸空间布局、外部参照、三维多段线、样条、倾斜坐标系及无法确定的嵌套岛不自动修补。PDF作为图片输入，仍需要视觉模型和尺寸确认，不能与DXF/DWG精度等同。

测试件为本项目自建圆角板，120×80×8毫米、四个Ø8通孔及30×12毫米长圆槽；不是用户研究项目的CAD数据。实际验收与失败尝试保存在本机artifacts/runtime，均不进入源码或EXE发布包。

0.7.0测试补充阶梯件120×80×36毫米，基座厚12毫米，后侧凸台80×32×24毫米。五个孔覆盖两处不同台阶的盲孔、普通通孔、通底沉孔和盲底沉孔。另一份圆角孔板为100×70×20毫米，验证圆弧外轮廓、缺深度澄清及深度补充。实际验收以对应发行版release-acceptance.json为准。

0.8.0测试图为自产斜面壳座120×80×50毫米与圆弧拱座100×60×60毫米，包含真实DIMENSION、LEADER和孔径/深度/角度标注，不使用嵌入的特征JSON。斜面图覆盖X/Y/Z三方向孔及82°、90°沉头、118°钻尖；圆弧图覆盖R50拱顶、侧向通孔/平底沉孔与含钻尖总深度。实际保存重开及EXE验证结果以对应发行包验收记录为准。
