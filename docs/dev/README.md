# 内部开发工具

本目录下的脚本是开发/调试用的内部工具，**不作为面向用户的 CLI 产品**。

这些脚本直接调用 Cognee 内部 API（`cognee.remember`、`cognee.recall`），
绕过 `deep_obsidian` 公共 API。仅用于：

- 快速验证 Cognee pipeline 行为
- 调试摄入/召回问题
- 开发阶段的手动测试

**不要在生产环境或用户文档中引用这些脚本。**
