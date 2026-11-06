# 本机2024兼容修改

## 0.11 原生标准孔与真实螺纹

`engineering/standard_holes.py` 和 `engineering/threads.py` 参考 MIT 项目
hjbaard/SolidWorks-MCP 的提交 `ddcefc0cfa056002ff8eb8bdb186818ad52dc2f1`，
保留 `release_tools/licenses/HJBAARD-MIT.txt` 的许可及署名。只适配原生 HoleWizard5、
ThreadFeatureData、库规格校验和精确孔位流程，没有接入其窗口操作或任意代码入口。

本地增加六向平面与孔位读回、独立钻深/牙长、标准孔配合回读、真实牙型的理论底径、
材料长度门禁、原生螺旋边的螺距/旋向测量及保存重开验证。牙长使用 typed IFeature
的 ModifyDefinition 修改，避免2024动态派发的参数类型错误。

PitchOverride=false 时，Pitch 字段可保留未生效默认值。本地以实际原生螺旋边核验有效螺距，
并单独保留默认字段，不能只按名称或未启用参数认定几何。应用不添加 Fix；标准孔截面和
螺纹库自身的固定关系由 `engineering/feature_quality.py` 原样统计、标识原生管理，
不通过删除库约束或抹去计数伪造零Fix。原点孔位允许零独立坐标尺寸，但必须零自由度且无Fix。

上述路径在本机2024验证。2026、细牙/英制/管螺纹及非Z轴真实牙型没有本机验收。

vendor/source-manifest.json 保留复制时的上游原始 SHA-256。上游技能安装目录未改。

本目录 server.py 包装原服务，固定2024、使用单一STA线程和跨进程锁，并去除
窗口消息恢复工具。五个原生辅助工具重新注册到同一执行器。新建文档预算保留
用户已加载的装配体组件，额外允许本轮8个文档。

vendor/solidworks-automation/scripts/sw_native_wire.cs 的 Bind 方法增加类工厂
回退。仅在已存在唯一SolidWorks进程，且PID与请求相同、实际版本为32.x时返回；
原有显式目标文档检查保留。补丁及原始文件副本位于 patches/。

2024原生C#写入操作仍需按具体任务验证。本次补丁只对几何检查完成只读实测。
