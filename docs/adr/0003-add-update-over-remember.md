# 使用 add()+update() 底层 API 而非 remember() 便捷入口

Cognee 提供两层 API：高层 `remember()`（add+cognify+improve 一步完成）和底层 `add()` + `cognify()` + `update()`（分步控制）。deep-obsidian 选择底层 API，放弃 `remember()`。

## 为什么

`remember()` 有两个不可绕过的限制：

1. **无法分离 add 和 cognify。** 用户初次导入可能有数百个文件，逐文件 `remember()` 等同于逐文件调 LLM，无法批量控制。`add()` 可以先写 Dataset 拿到 data_id，积攒后批量 `cognify()`。

2. **不返回 data_id。** `update()` API 是 Cognee 官方推荐的修改处理方式（delete-then-re-add），但它需要 data_id。`add()` 返回的 `PipelineRunInfo` 中包含 data_id，可供后续 `update()` 使用。`remember()` 的返回值结构不保证可提取 data_id。

3. **修改去重语义明确。** `update(data_id)` 执行的是先删后加——旧节点的图节点、边、向量嵌入被清除（共享节点保留），然后重新建图。这是 Cognee 文档明确描述的保证。`remember()` 是追加语义，重复调用会产生冗余数据。

## 权衡

- **代价**：多一步 API 调用（add → cognify vs remember），代码复杂度略增
- **收益**：批量 cognify 控制 LLM 消耗、data_id 跟踪支持增量更新、明确的修改去重语义
- **被拒绝的替代方案**：remember() + 回查 data_id。路径不明确，API 合约不稳定。
