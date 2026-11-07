# SolidWorks AI

English | [简体中文](README.zh-CN.md)

Build editable parts and assemblies in your own **SOLIDWORKS 2024** using natural language, reference images or dimensioned drawings. Separate models can plan/review and execute. CAD control uses native MCP/COM APIs, without mouse, keyboard, Computer Use or window-message automation.

## Download and start

Future updates follow the [release policy](release_tools/RELEASING.md): qualified regular releases, plain numeric versions, paired source/EXE downloads and credential exclusion.

**[Download Windows x64 — includes the EXE](https://github.com/zhu-chengdong/solidworks-ai/releases/download/v0.16.0/SolidWorksAI-0.16.0-windows-x64.zip)**

Current version: **0.16.0, regular release**. [Release notes, source and checksums](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.16.0).

All 11 existing public versions were promoted to regular GitHub releases on 2026-11-07. Historical `-rcN` identifiers, download names and original release notes are retained. [Latest release](https://github.com/zhu-chengdong/solidworks-ai/releases/latest).

1. Install and activate your own SOLIDWORKS 2024 on Windows x64.
2. Download the Windows ZIP and extract it completely.
3. Run `SolidWorksAI/SolidWorksAI.exe`. Keep `SolidWorksMCP.exe` and `_internal` beside it. No Python installation or command line is required.
4. For exact DXF/DWG tasks, upload the drawing and describe its views/depths. For AI tasks, save your own provider key once in **模型与密钥** (models and keys), then enter a natural-language request.

The interface is currently Chinese; the repository provides English and [Chinese instructions](README.zh-CN.md). GitHub's **Code → Download ZIP** downloads developer source; use the Windows link above to run the program.

Upload a parametric SLDPRT and describe local dimension changes. The app inspects actual driving parameters, edits a separate copy and verifies it after reopening.

See the [capability comparison and priorities](release_tools/CAPABILITY_ROADMAP.md).

## Version history

| Release | Main changes |
| --- | --- |
| [0.16.0](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.16.0) | Native assembly drawings, BOM, associated balloons and PDF |
| [0.15.0-rc4](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.15.0-rc4) | Add native manufacturing drawings with associated dimensions sections and PDF verification |
| [0.14.0-rc11](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.14.0-rc11) | Add verified materials and BOM with bounded MAX planning and stock edits |
| [0.13.0-rc7](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.13.0-rc7) | Add native editable planar slots and polygon pockets with STEP checks |
| [0.12.0-rc2](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.12.0-rc2) | Add associative hole patterns and mirrors with geometric acceptance |
| [0.11.0-rc3](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.11.0-rc3) | Add ISO Hole Wizard and geometrically verified metric threads |
| [0.10.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.10.0-rc1) | Add verified native fillets and chamfers to structured part plans |
| [0.9.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.9.0-rc1) | Add native local dimension editing through natural language |
| [0.8.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.8.0-rc1) | Sloped/circular-arc three views, three-axis holes, drill points, countersinks and bilingual documentation |
| [0.7.0-rc3](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.7.0-rc3) | Stepped three views, flat-bottom blind holes, counterbores and native readback |
| [0.6.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.6.0-rc1) | Exact DXF/DWG modelling and PDF uploads |
| [0.4.0-rc13](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.4.0-rc13) | View orientation/labels, automatic preview correction and versioned delivery |

Older tags, original notes and downloads are retained. See the [full changelog](CHANGELOG.md), [中文更新记录](CHANGELOG.zh-CN.md) and [all releases](https://github.com/zhu-chengdong/solidworks-ai/releases).

## Assembly drawings

Select **装配工程图**, add a ZIP containing one SLDASM and all its SLDPRT dependencies, then request a drawing with BOM, item-number balloons and PDF. The app copies and relocates the dependencies locally and preserves the originals. BOM quantities and native per-instance associations are checked after reopening, and the actual PDF text is matched before visual review.

Qualified scope: one flat resolved assembly on A3, first-angle front/top plus isometric views. The seven-instance bracket/shaft/plate example has five native BOM rows and seven associated balloons. Nested/exploded/assembly-section/multisheet workflows remain separate. See [native API scope](engineering/ASSEMBLY_DRAWING_API.md).

## Native manufacturing drawings

Select **制造工程图** (manufacturing drawing), upload one SLDPRT and enter a request such as `生成A3第一角主俯左三视图，标注外形和孔位，增加经过孔中心的A-A全剖，导出PDF`.

The qualified single-solid route creates A3 landscape front/top/left first-angle views, associated overall and top-entry circular-hole position dimensions, genuine hole callouts and one horizontal/vertical straight full section. Native readback checks dimensions, hole variables, cutting arrows and actual hatching after save/reopen. The real PDF is checked for values, clipping and dimension-text overlap, followed by visual review using your configured vision-capable planner. Outputs include editable SLDDRW, copied SLDPRT dependency, PDF, preview and a checksummed ZIP; the uploaded source stays unchanged.

This produces nominal drawings. Supply and review manufacturing tolerances and processes separately. Side/bottom-entry hole coverage, offset sections, assembly drawings and multiple sheets are outside this batch; unsupported requests stop explicitly. No geometry or PDF is generated through desktop automation. See [native API scope](engineering/MANUFACTURING_API.md).

## Drawings to native parts

Select **添加二维图纸** (add 2D drawing) for DXF, DWG or PDF. The deterministic vector route needs no API key and uses **zero model API tokens**. For an extrusion, enter `厚度8毫米，所有内轮廓均为通孔` (8 mm thickness; all inner contours through). Multiple independent views are numbered; choose the required view before proceeding.

For orthographic drawings, enter `按三视图及孔标注建模` (build from three views and hole callouts). Supply FRONT/TOP/RIGHT or Chinese labels, or specify numbered views. Supported exteriors are consistent orthogonal prismatic silhouette intersections, including steps, slopes and circular arcs. Native line/arc sketches, extrusions and outside cuts preserve analytical geometry; arbitrary freeform reconstruction is not claimed.

Leaders associate circles with unique hole specifications. Entries use TOP along −Z, FRONT along +Y, or RIGHT along −X, on complete axis-normal planar faces.

| Feature | Callout example |
| --- | --- |
| Flat-bottom blind hole | `H1 DIA8 BLIND DEPTH12 FLAT BOTTOM` |
| Counterbore | `H2 DIA6.6 THRU CBORE DIA13 DEPTH5` |
| Drill point; cylindrical depth | `H3 DIA8 BLIND CYL DEPTH18 POINT118` |
| Drill point; total depth | `H3 DIA8 BLIND TOTAL DEPTH20 POINT118` |
| Countersink | `H4 DIA6.6 THRU CSK DIA13 ANGLE90` |

Missing units, depths, bottom shape, depth convention or included angle are clarified before writing CAD. Dimension conflicts, unexplained hidden lines, intersecting hole envelopes and reverse/oblique entries stop the exact route. Single-view exact extrusions and through slots remain available. DWG is converted through native SOLIDWORKS Model-space import, restoring export options and preserving the original upload/hash. The interface offers stepped, sloped/side-hole and curved/drill-point example DXFs.

After saving and reopening, checks cover exact volume/bounds, real cut depths/end conditions, cylinder intervals, cone angles/end radii/apices, fully defined sketches and zero Fix constraints. Curved projection verification evaluates native B-Rep edges using a 0.002 mm chord target and 0.025 mm projection tolerance; sampling does not create CAD geometry. Outputs include SLDPRT, AP214 STEP with solid-count verification, four native previews and a checksummed ZIP. See [scope and sources](drawing2cad/REFERENCES.md).

PDF uploads of 1–4 pages are rendered locally into reference images for the existing vision-model workflow. That route needs critical dimensions and incurs the chosen provider's charges; it does not recover exact CAD vectors from scans.

## Natural-language, image and assembly workflows

Configure separate planning/review and execution models, including compatible OpenAI and DeepSeek providers. Supported engineering plans include hole plates, L brackets, shafts, open rectangular enclosures and bounded extruded/revolved profiles. Missing dimensions trigger questions.

Assemblies accept generated or uploaded SLDPRT parts, repeated instances, BOMs and native coincident/distance/concentric mates. They check component position, fixed/fully constrained status and interference after reopening, then package SLDASM dependencies, STEP and BOM. Arbitrary assembly imports, moving mechanisms and gears are outside the tested scope. Passing geometry checks does not establish load capacity, fit or manufacturing readiness.

Image workflows support bounded extruded profiles, up to 12 through holes, axisymmetric parts, elliptical-section lofts and a cartoon-aircraft template. Supply dimensions, or explicitly permit appearance approximation. The aircraft option can use an estimated 160 mm example length and records assumptions; intersecting separate bodies and summed volumes are not a validated manufacturing solid. Models preserve editable native features. The planner reviews native previews and may request one preview-only correction followed by another review; new pictures cannot bypass geometry/mate failures. Revisions retain earlier models and delivery packages.

## Optional quota routing

**额度与路由** (quota and routing) supports a local Magpie bridge to ModelScope. Save your own access token, refresh quota/models and install/start the verified Magpie Windows background program. Ports 3425/3430 must be free. Simple/standard/complex task routes use configured model IDs; free-only routing stops on missing/zero verified quota and never silently falls back to paid providers. The upstream token stays in Windows Credential Manager, outside Magpie.

Real free-channel model/assembly acceptance remains pending a usable token and quota. The software does not supply credits, shared accounts or guaranteed daily benefits. Configuration and status displays do not prove a real upstream model call.

## Credentials and local operation

Each user provides their own account and pays their provider. Keys stay in that Windows user's Credential Manager; plain settings and release packages contain no keys. Task prompts, tool results, reference images and review previews are sent to the selected provider, with SDK tracing uploads disabled. Native CAD binaries remain local; planning receives structured geometric readback.

Release settings and outputs live under `%LOCALAPPDATA%\SolidWorksAI` and survive upgrades independently of the program folder. Use the interface to download outputs/open their folder. Do not copy credentials between Windows accounts. Closing the browser leaves the service running; choose **退出应用** (exit application) to stop it.

Existing CAD is copied before modification. Stop prevents further calls; accepted native calls are allowed to return and are not automatically replayed. Handle licence/template dialogs manually if needed. Native acceptance targets SOLIDWORKS 2024 on the development machine; other years and real modelling on another computer remain unqualified.

## Development and provenance

Use Windows x64/Python 3.12, install `requirements-desktop.txt`, then run `python launch-workbench.pyw` for the workbench or `python server.py` for MCP stdio. Test with `python -m unittest discover -s tests -v`. Install `pyinstaller>=6.22,<7` and run `python release_tools/build.py --tag <unique-version>` to build. Artifacts stay in ignored `releases/`; the build script does not publish them.

Project code is MIT licensed. The pinned `wzyn20051216/solidworks-automation-skill` snapshot retains its licence/provenance in `vendor/`; compatibility patches are documented in `PATCHES.md`. Bounded image compilation reuses MIT code from `czuryk/SolidworksMCP`, with licence and source commit in `integrations/czuryk/provenance.json`. Windows packages include dependency notices/licences. Optional PDF review tools, neural weights and external solvers are not bundled. SOLIDWORKS is its owner's trademark; this independent project includes neither SOLIDWORKS nor a licence.
