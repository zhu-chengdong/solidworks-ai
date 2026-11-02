# 本机2024兼容修改

vendor/source-manifest.json 保留复制时的上游原始 SHA-256。上游技能安装目录未改。

本目录 server.py 包装原服务，固定2024、使用单一STA线程和跨进程锁，并去除
窗口消息恢复工具。五个原生辅助工具重新注册到同一执行器。新建文档预算保留
用户已加载的装配体组件，额外允许本轮8个文档。

vendor/solidworks-automation/scripts/sw_native_wire.cs 的 Bind 方法增加类工厂
回退。仅在已存在唯一SolidWorks进程，且PID与请求相同、实际版本为32.x时返回；
原有显式目标文档检查保留。补丁及原始文件副本位于 patches/。

2024原生C#写入操作仍需按具体任务验证。本次补丁只对几何检查完成只读实测。
