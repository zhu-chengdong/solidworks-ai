# Capability comparison and priorities / 能力对比与优先级

Checked on 2026-11-06. Peer rows below describe their published implementation or documentation; their CAD acceptance has not been reproduced on this computer. Our release claims require local native SOLIDWORKS tests, save/reopen, geometric checks and packaged-app acceptance. Tool counts are not evidence that a workflow is reliable.

核查日期为2026-11-06。以下同类项目能力依据公开代码与文档，未在本机逐项复测。我们的发行能力以原生实测、保存重开、几何核验及EXE验收为准。

| Peer project | Relevant capabilities documented by its authors |
| --- | --- |
| [hjbaard/SolidWorks-MCP](https://github.com/hjbaard/SolidWorks-MCP) | Native patterns/mirrors, arbitrary pockets/slots, materials, parameterized joints and drawings. / 原生阵列镜像、口袋槽口、材料、关节和工程图。 |
| [czuryk/SolidworksMCP](https://github.com/czuryk/SolidworksMCP) | Feature/body patterns, mirrors, shells, sweeps and measured geometry workflows. / 特征实体阵列、镜像、抽壳、扫描与测量复核。 |
| [aryesil/SolidworksMCP](https://github.com/aryesil/SolidworksMCP) | Drawing annotations/sections, configurations/properties, assembly editing, sheet-metal flat patterns and manufacturing packages; its stated target includes 2026. / 工程图、配置属性、装配编辑、钣金展开和制造包，作者声明覆盖2026。 |
| [rdolan5/solidworks-mcp-2](https://github.com/rdolan5/solidworks-mcp-2) | CAD, drawing/configuration operations and CAM workflows; CAM needs installed add-in and suitable licensing. / CAD、工程图、配置和需许可的CAM流程。 |

## Current implementation order / 当前实施顺序

1. **Associative hole patterns and mirrors.** Linear/grid and full-circle patterns, XZ/YZ mirrors, seed linkage and independent verification of actual holes. First qualified scope is local +Z Hole Wizard clearance/counterbore/countersink seeds. General body/component mirrors and tapped-thread replication remain separate work. / 原生孔特征线性网格、圆周阵列和镜像，核对种子关联与实际孔位；整体实体、组件和螺纹阵列另行验收。
2. **Slots and polygon pockets.** Editable arc/line sketches and blind/through native cuts, first on local +Z planar entries; exact removal, sketch constraints and STEP verification. / 可编辑圆弧长圆槽与多边形口袋，首先验收顶面盲切和贯穿。
3. **Materials, physical properties and BOM.** Native material assignment or explicit custom density, measured mass and volume, and honest treatment of unassigned materials. / 原生材料或明确自定义密度，实际质量体积与BOM；未知材料不能按默认密度冒充已知质量。

## Remaining priorities / 后续缺口

| Priority | Gap | Required qualification |
| --- | --- | --- |
| Qualified batch / 已验收批次 | Flat assembly drawings / 扁平装配工程图 | A3 first-angle front/top plus isometric, genuine parts-only BOM, per-instance associated balloons, native save/reopen, actual PDF cell/number checks and dependency ZIP. Seven-instance bracket/shaft/plate fixture has five BOM rows and seven balloons. Nested/exploded/assembly-section/multiple-sheet drawings remain separate. / 原生BOM、每实例关联气泡、保存重开、真实PDF和完整依赖包；七组件实测为五行BOM、七个气泡。 |
| Qualified batch / 已验收批次 | Nominal part drawings / 零件标称工程图 | A3 first-angle front/top/left, associated overall/hole-position dimensions, top-entry native hole callouts, straight full section, save/reopen and actual PDF inspection. Tolerances, offset/multiple sections, assembly drawings and multiple sheets remain separate. / A3第一角主俯左、关联外形孔位尺寸、顶面孔标注、直线全剖与真实PDF核验；公差、阶梯或多个剖视、装配图及多页另行实施。 |
| Next | Mechanism mates / 运动机构 | Angle/limit/hinge mates, solver-driven range checks, interference across travel; motor animation alone does not prove mechanism correctness. |
| Next | Configurations and variants / 配置族与变型 | Real configuration isolation, parameter cycles, active-configuration readback and reference preservation. |
| Later | General body/component patterns, advanced sweeps, shells and ribs / 更通用实体操作 | Dedicated native geometric and source-preservation tests per operation. |
| Later | STL/3MF print packages and sheet-metal flat DXF / 打印与钣金 | Closed manifold mesh checks or native flat-pattern topology/units verification. |
| Later | CAM/FEA/PDM and 2026 / CAM、仿真、PDM与2026 | Verify actual installation, entitlement and results. They are not implied by an API member or by a peer's feature list. |

The current locally qualified CAD environment is SOLIDWORKS 2024. Each validated batch receives its own release number and Windows/source downloads. Earlier releases remain available.

当前本机验收环境为SolidWorks2024。每批通过后单独发布版本号、Windows包和源码包，保留历史发行版。
