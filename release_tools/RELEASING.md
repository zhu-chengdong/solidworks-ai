# Release policy / 发布规则

## 简体中文

自2026-11-07起，新的软件版本在相关测试和验收通过后直接正式发布，无需再次询问常规发布许可。

- 版本号只用`MAJOR.MINOR.PATCH`，例如`0.16.0`和`0.16.1`。Git标签加`v`前缀，不再新增`rc`、`alpha`或`beta`后缀。
- 先更新`workbench/webserver.py`中的`VERSION`，再用同一个版本号构建。实际EXE启动回报的版本、标签、源码ZIP、Windows ZIP、校验和及更新说明必须一致。
- GitHub源码和Windows EXE一起交付。回归、相关原生CAD实测、独立目录EXE测试和真实已保存凭据扫描通过后才发布；版本格式检查不能代替实际CAD验收。
- 上传阶段可使用临时草稿。两个ZIP、SHA256和验收摘要齐全且校验通过后，将Release公开为正式发布并设为Latest；下载回读核对实际文件哈希。
- 每版写清版本号、简要中文更新内容、英文对应说明和实际验收范围。保留历史版本、旧标签和原始安装包。
- 只上传审计过的公开源码范围。API密钥、凭据、本机设置、运行记录和研究模型不进入GitHub或EXE包。

已公开的历史`-rcN`标签和文件名继续保留。仅更新文档或发布流程时，不替换已经验收的历史EXE；流程变更随下一次软件版本的源码和EXE统一交付。

## English

From 2026-11-07, publish qualified software updates directly as regular releases without another routine approval request.

- Use plain `MAJOR.MINOR.PATCH`, for example `0.16.0` or `0.16.1`, and a matching `v` Git tag. Do not add new prerelease suffixes.
- Update `VERSION` in `workbench/webserver.py` before building. Match the actual tested executable's reported version, tag, source ZIP, Windows ZIP, checksums and release notes.
- Deliver audited source and Windows executables together after relevant regression, native CAD, relocated executable and actual stored-credential checks pass. Version validation does not replace real CAD qualification.
- A temporary draft may hold uploads. Publish the complete, verified asset set as a regular release and Latest, then download and verify its hashes.
- Maintain concise Chinese and English change descriptions, tested scope and historical releases. Exclude keys, vault contents, local state, logs and private research models.

Keep historical `-rcN` identifiers and assets. Documentation/workflow-only changes do not replace qualified historical binaries; include the workflow changes with the next paired software delivery.
