# SolidWorks AI

[English](README.md) | 简体中文

[完整更新记录](CHANGELOG.zh-CN.md) · [全部历史版本与下载](https://github.com/zhu-chengdong/solidworks-ai/releases)

## 下载与开始使用

**[点击下载 Windows 版（内含 EXE）](https://github.com/zhu-chengdong/solidworks-ai/releases/download/v0.14.0-rc11/SolidWorksAI-0.14.0-rc11-windows-x64.zip)**

当前版本为 **0.14.0-rc11 预发布版**。[发行说明、源码和校验和](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.14.0-rc11)。

1. 准备 Windows 64 位电脑，并安装、激活 SolidWorks 2024。
2. 点击上面的下载链接，下载后右键压缩包，选择“全部解压缩”。
3. 打开解压后的 `SolidWorksAI` 文件夹，双击 `SolidWorksAI.exe`。保留同目录的 `SolidWorksMCP.exe` 和 `_internal` 文件夹。
4. 精确DXF/DWG拉伸建模可直接上传图纸并输入厚度等要求。其他AI任务在“模型与密钥”中填写自己的API Key，保存后用自然语言输入建模需求。

发布包自带运行环境，无需安装 Python 或输入命令行。每位用户使用自己的 API 账户和额度，密钥保存在本人 Windows 凭据管理器中。

GitHub 的 `Code → Download ZIP` 下载的是开发源码；直接使用程序请点击上面的 Windows 版下载链接。

用自然语言操作自己电脑上的 SolidWorks。可分别选择模型理解与复核需求、
通过原生 MCP / COM 调用建模工具。无需鼠标、键盘或窗口消息自动化。

这是 Windows x64 的预发布候选版，当前验证目标为 SolidWorks 2024。它不是
SolidWorks 的替代品，也不包含 SolidWorks 软件或许可证。其他年份尚未验收。


上传SLDPRT后可以直接输入“厚度改成12毫米，两个孔改成直径10毫米，其余保持”。程序先读取驱动参数，修改工作副本并保存重开验证。

参见[同类项目对比与后续优先级](release_tools/CAPABILITY_ROADMAP.md)。

## 版本历史

| 版本 | 主要更新 |
| --- | --- |
| [0.14.0-rc11](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.14.0-rc11) | 原生材料、质量BOM与MAX预算控制 |
| [0.13.0-rc7](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.13.0-rc7) | 可编辑长圆槽与多边形口袋 |
| [0.12.0-rc2](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.12.0-rc2) | 原生孔阵列与镜像 |
| [0.11.0-rc3](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.11.0-rc3) | 标准孔与真实内外螺纹 |
| [0.10.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.10.0-rc1) | 自然语言圆角倒角 |
| [0.9.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.9.0-rc1) | 自然语言局部改模 |
| [0.8.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.8.0-rc1) | 斜面与圆弧三视图、三方向孔、钻尖、沉头；中英文说明 |
| [0.7.0-rc3](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.7.0-rc3) | 阶梯三视图、平底盲孔、圆柱沉孔及原生回读 |
| [0.6.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.6.0-rc1) | DXF/DWG精确建模与PDF上传 |
| [0.4.0-rc13](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.4.0-rc13) | 三视图朝向与标识、自动补图复核及历史交付 |

旧版发行说明、标签及安装包保留。详细变更见[更新记录](CHANGELOG.zh-CN.md)。

## 普通用户

### 二维图纸生成三维零件

点击“添加二维图纸”，选择DXF、DWG或PDF。DXF/DWG走精确矢量流程，例如输入
“厚度8毫米，所有内轮廓均为通孔”。多个轮廓时程序先显示编号识别图，再回复
“使用视图1”即可继续。这个受限流程无需配置API Key，Token消耗为0。

三视图可输入“按三视图及孔标注建模”。需要FRONT/TOP/RIGHT或中文视图标识，亦可在对话中指定编号。
联合重建覆盖直角阶梯、斜面和圆弧轮廓的正交棱柱交集；平底盲孔、通孔和圆柱沉孔支持TOP/Z、FRONT/Y、RIGHT/X三方向，分别读取局部平面入口与孔深。
例如图纸孔引线标注`H1 DIA8 BLIND DEPTH12`或`H2 DIA6.6 THRU CBORE DIA13 DEPTH5`。
钻尖标注例如`H1 DIA8 BLIND CYL DEPTH18 POINT118`或`TOTAL DEPTH20 POINT118`；沉头例如`H2 DIA6.6 THRU CSK DIA13 ANGLE90`。圆柱段深度与含钻尖总深度分开处理，缺少孔深、底形、深度定义或夹角先询问。页面提供阶梯、斜面侧孔和圆弧钻尖三份示例图纸。

单视图继续支持等厚拉伸件、精确直线/圆弧、圆孔和贯穿闭合槽，保留图纸原文件。
DWG由本机SolidWorks原生转换，只读取Model空间；已处理原生导出打散孔引线的情况。
程序核对单位、标注冲突、保存重开后的孔深、圆柱段和平底、三视图投影及草图可编辑性。
外形保留精确原生直线/圆弧，锥形孔用旋转切除创建；保存重开后回读圆柱段、锥面角度与端点、特征定义和精确体积。曲线投影核验使用0.002毫米弦差目标及0.025毫米投影容差，这些采样不用于创建CAD。孔必须从约定视图的完整坐标轴法向平面进入。反向/斜向孔、相交孔包络、未解释的隐藏结构、任意自由曲面、螺纹及装配重建不属于此入口范围。详细来源及范围见
[`drawing2cad/REFERENCES.md`](drawing2cad/REFERENCES.md)。

PDF支持1至4页，在本机转成参考图片，仍需支持图片的模型和关键尺寸确认。
PDF路径的模型调用按所选供应商计费，不承诺从扫描图恢复精确CAD坐标。

### 可选的免费额度与 Magpie 路由

打开左下角“额度与路由”，在密码框保存自己的魔搭访问令牌，然后刷新余额和模型。
令牌由 Windows 凭据管理器保管，Magpie 只连接本机桥接接口，不获得真实上游令牌。
点击“安装或启动 Magpie”从官方 GitHub 下载并校验 Windows 后台程序，首次需要联网。
本机后台使用3425和3430端口，与已有其他Magpie实例同时使用时会提示端口冲突。

选择基础、常规、复杂三个档的准确模型ID，测试工具调用，再启用免费任务池。
程序按本地规则判断任务难度，装配体和图片走复杂规划，执行走常规档，关键复核用复杂档。
模型实际返回、强度和用量会记录；额度不足不会切换到付费API。

魔搭每日赠送额度需本人在官网登录领取；软件不模拟网页登录活动。
“管理 Magpie 签到账号”可在隔离的Magpie管理页添加支持签到的账号。
启用每日检查后，在本工作台运行期间每天检查一次；未配置账号、验证码和失败会如实显示。
这不是Windows关机后仍运行的定时服务。其他Agent的订阅登录自动发现已关闭。
未知余额显示未核实，不作为零余额或领取成功。免费模型的稳定性需以实际任务验证。

1. 在自己的电脑安装并激活 SolidWorks 2024，先确认能够正常启动、新建零件。
2. 下载 Windows 发布压缩包并完整解压，双击 `SolidWorksAI.exe`。
   保留同目录的 `SolidWorksMCP.exe` 与 `_internal` 文件夹。
3. 打开“模型与密钥”，填写自己的 API Key，点击“保存并测试”。
4. 输入需求，例如“创建一个边长10毫米的立方体，保存并导出STEP”。
5. 按图片建模时点击“添加参考图片”，选择建模方式，补充尺寸后发送。
   支持PNG、JPG和WebP，每张最多8MB，每个任务最多4张。上传本机后，点击发送才交给模型。
6. 组装已有零件时点击“添加零件文件”，选择SLDPRT，再描述位置、间隙和配合关系。
   每个文件最多50MB、每次最多12个。程序自己读取尺寸，原始文件保持不变。
7. 修改刚完成的任务时直接补充，例如“把板面净间隙改成15毫米，其他保持”，另存新修订。
8. 零件/装配预览有问题时可点击“重新复核预览”。系统在新任务中复核已有模型，遇到视图朝向、标签、缺图等问题时自动重出预览并再次复核，每个任务最多修正一次。已修正模型的新任务使用递增的预览编号，模型与原交付包保留。失败或中断的原生调用不会自动重放。

发布包已包含 Python 运行环境，用户无需安装 Python、运行命令行或注册 MCP。
界面在默认浏览器打开，服务仅监听本机回环地址。

默认理解与复核模型为 OpenAI `gpt-6.1-sol`，执行模型为 `gpt-5.4-mini`；可在设置中
更换为自己账户可用的模型。提供 OpenAI、DeepSeek 和 OpenAI 兼容接口，两个角色
可以分别选择供应商。兼容接口不代表所有模型均已实测，模型必须支持工具调用。

规划/复核与执行均可单独保存思考强度。DeepSeek 支持关闭、Low、High、MAX；
显式选择 MAX 后，各角色都会发送最高强度参数，失败时不会自动降低强度。
任务记录包含实际请求强度、响应 ID、耗时和 Token 用量，不包含推理正文。

每人使用自己的 API 账户，费用与额度由所选供应商结算。程序不提供共享账户或额度。
API Key 存储在当前 Windows 用户的凭据管理器，普通配置文件不包含 Key。任务描述、
工具结果、参考图片及复核预览会发送给选择的模型服务，SDK 追踪上传已关闭。
理解模型需要支持图片输入，设置中有对应选项；执行模型只接收文字方案和工具结果。

发布版设置、日志与模型产物位于 `%LOCALAPPDATA%\SolidWorksAI`，与程序目录分离，
升级时保留。产物在界面里下载或打开目录。不要在不同 Windows 账户间复制凭据。
关闭网页后服务仍运行；使用“退出应用”关闭服务。

修改现有文件前另存工作副本，任务输出使用独立目录。停止按钮阻止后续操作，
已进入 SolidWorks 的原生调用需等待返回。出现许可证或模板对话框时本人处理。

## 范围与状态

SolidWorks 2024 已有本机验证覆盖新零件、基础草图与拉伸、保存、重开、STEP 导出、
预览与原生几何读取。上游其他工具保留原能力等级，不将工具数量当作全部已验收。
复杂曲面、工程图及制造适用性需逐项复核。

自然语言规划接入孔板、L形支架、圆轴、开口矩形壳体及拉伸/旋转轮廓，关键尺寸不足
时先询问。装配支持生成零件或选择自己的SLDPRT，输出SLDASM与完整依赖ZIP；
相同零件可有多个实例，BOM按实例计数。已接入重合、距离、同心原生配合，核对
组件位置、固定/完全约束状态和干涉，保存重开后复核，并导出STEP和原生预览。
直接导入任意SLDASM的完整依赖、复杂机构运动、齿轮和工程图不属于本轮验收范围。
配合与尺寸通过不代表承载、装配公差或制造可行性通过。

原生零件文件只保存在本地；规划模型接收尺寸、体积、圆柱面与坐标等读取结果，
不接收CAD二进制文件。自己的已有任务采用完整参数方案生成新版本，保留未修改参数。

图片建模当前接入单个拉伸轮廓、最多12个沿厚度方向贯穿圆孔与轴对称旋转件。
圆润造型还支持有界的椭圆截面放样和卡通飞机部件模板，保留独立实体及配色。
点击“图片建卡通飞机”，上传参考图后直接描述需求。外观尝试允许估算尺度，
未指定时飞机可采用约160毫米的示范长度；隐藏结构的对称假设会明确列出。
机身、机腹、机翼、尾翼和玻璃逐批保存，界面显示进度，批次之间可以停止。
飞机部件在接合处相交，体积求和不代表合并体积或制造质量。SLDPRT保留特征树，
STEP用于交换实体几何；这类模型是外观近似，交付前需确认比例与设计意图。
原生输出文件名包含任务标识，避免打开多个同名文档时交换格式转换混淆。
STEP使用AP214并核对实体数量，导出结束后恢复原系统选项。
原生草图使用端点重合、水平/垂直关系和驱动尺寸，验收要求完全定义且零Fix固定。
默认“按尺寸建模”，缺少厚度等必要
尺寸时先询问；“外观尝试”允许估计尺度和比例，估计项会列出并要求复核。
单张图片不保证恢复隐藏结构，尚未接入的其他孔槽、复杂曲面或装配会说明能力缺口。
上游原始源码固定在指定提交；本地只复用受限几何编译器，不启动上游服务器、
任意Python执行或窗口恢复工具。模块注册、模型供应商和CAD传输分别维护。

Windows 发布候选包会检查界面、真实 MCP 协议、依赖导入和另一目录启动；这些检查
不等同于在另一台电脑完成真实模型调用和 CAD 建模。发布前应查看随包验收记录。
PDF 文字布局复核的可选 PyMuPDF、神经网络权重与外部求解器不包含在此发布包中。

## 开发者

使用 Windows x64、Python 3.12，在虚拟环境安装 `requirements-desktop.txt`；运行
`python launch-workbench.pyw` 启动源码版。`python server.py` 为标准 MCP stdio 入口。
源码版默认在项目目录保存非秘密数据。

运行 `python -m unittest discover -s tests -v` 检查回归。构建 Windows 包时安装
`pyinstaller>=6.22,<7`，运行 `python release_tools/build.py --tag <唯一版本号>`。
构建输出在忽略的 `releases/` 中。构建脚本不会推送 GitHub 或自动发布。

## 许可与来源

本项目代码采用 MIT 许可。上游 `solidworks-automation-skill` 的 MIT 版权与来源保留在
`vendor/solidworks-automation/LICENSE` 及 `vendor/source-manifest.json`；兼容补丁见
`PATCHES.md`。第三方运行库各自适用其许可，随 Windows 包附许可证文本及依赖清单。
图片建模编译器复用 `czuryk/SolidworksMCP` 的MIT源码，提交来源见
`integrations/czuryk/provenance.json`，原始版权和许可完整保留。
SolidWorks 是其权利人的商标；本项目为独立工具。
