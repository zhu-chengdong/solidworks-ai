# 二维图纸到原生参数化零件

核实日期为2026-11-05。本模块是本项目的受限实现，不包含神经网络权重或任意代码执行。

参考项目及采用范围：

- [Drawing2CAD](https://github.com/lllssc/Drawing2CAD)，MIT，核对README提交 `e39777723e83d0d2244d008497e8e1f21c193caa`。参考矢量视图归一化、视图与建模序列分离的思路。其训练/推理环境需要CUDA；本项目未移植其模型、训练数据或推理代码，也不宣称实现其论文的通用重建能力。
- [CAD2Program](https://github.com/manycore-research/CAD2Program)，核对README提交 `b7790a6a39f372cbf6a29bf89c5cac20b20e9012`。公开仓库当前是项目展示网站，未提供可直接集成的完整推理实现。本项目未复制网站代码或素材。
- [ezdxf](https://github.com/mozman/ezdxf)，MIT，Copyright (c) 2020 Manfred Moitzi。[EdgeSmith文档](https://ezdxf.readthedocs.io/en/stable/edgesmith.html)说明精确圆弧与链构建方法；本项目不使用自动补缝来修改制造轮廓。实际依赖版本由发行包DEPENDENCIES.json记录。
- [SolidWorks 2024 IImportDxfDwgData.ImportMethod](https://help.solidworks.com/2024/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IImportDxfDwgData~ImportMethod.html)。DWG只导入Model空间，明确激活Model图纸并暂时设置仅导出当前图纸；结束后恢复导出选项。真实测试发现默认多图纸导出会把图框放入模型空间，因此禁止沿用默认导出选项。
- [pypdfium2](https://github.com/pypdfium2-team/pypdfium2)，PDFium包装。只在本机将1至4页PDF渲染成受限尺寸参考图片。运行库及PDFium版权许可随EXE依赖元数据保留。

当前可验收范围：

- DXF模型空间、DWG的Model空间，平面LINE、ARC、CIRCLE、LWPOLYLINE以及旧式二维POLYLINE。图块支持受限展开，保留变换后的真实几何。
- 等厚拉伸、圆孔及其他闭合内轮廓的贯穿切除。精确圆弧创建为原生圆弧，采样只用于轮廓有效性及二维预览。
- 多个独立外轮廓会先出编号识别图，请用户指定视图；厚度和贯穿意图必须明确。程序不会把三个视图拉伸成三个零件。
- 未声明单位、非毫米图纸未声明厚度单位、尺寸文字覆盖或DIMLFAC与几何冲突、开放/分叉/接触/自交轮廓会停止并询问。标注冲突仅在用户明确“忽略标注”后按坐标继续。
- 保留原图与SHA256，完全定义草图、真实驱动尺寸、零Fix、原生拉伸、保存重开检查、体积/极值尺寸/圆柱面校核、AP214实体计数、四个原生相机视图、带SHA256的ZIP。
- 支持的精确矢量路径不调用模型、不要求API密钥，也不回退到付费API。

未覆盖任意三视图几何推断、自动恢复盲孔/沉孔/螺纹、曲面和装配。DWG纸空间布局、外部参照、三维多段线、样条、倾斜坐标系及复杂嵌套岛不自动修补。PDF作为图片输入，仍需要视觉模型和尺寸确认，不能与DXF/DWG精度等同。

测试件为本项目自建圆角板，120×80×8毫米、四个Ø8通孔及30×12毫米长圆槽；不是用户研究项目的CAD数据。实际验收与失败尝试保存在本机artifacts/runtime，均不进入源码或EXE发布包。
