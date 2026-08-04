# ADR 0002: 双层图架构

**状态**: 提议中  
**日期**: 2026-08-02  
**决策者**: 工程讨论

---

## 背景

Obsidian Markdown 文件包含大量结构化信息（`[[wikilinks]]`、frontmatter、tags），这些信息本身定义了文档间的关系。如果全部交给 LLM（Cognee cognify 阶段）来理解，既浪费 token 又可能产生遗漏或幻觉。用户希望结构信息由代码直接写入图，语义信息由 LLM 补充。

## 决策

采用 **双层图架构**：

1. **结构层图**（适配层负责）  
   - 解析 Markdown 提取 `[[wikilinks]]`、frontmatter tags、YAML 属性  
   - 将这些信息打包为 `DataItem.external_metadata` 传入 Cognee  
   - Cognee cognify 阶段能看到这些 metadata，避免了重复 LLM 推理

2. **语义层图**（Cognee 负责）  
   - `cognee.remember()` → `cognee.cognify()` 触发 LLM 分析文本内容  
   - 生成的节点和边（实体、关系、主题）与结构层图合并

3. 最终查询时，用户面对的是 **统一知识域** = 结构层 + 语义层

## 为什么不直接操作 Cognee 底层图 API？

Cognee 内部图 API（Ladybug/Neo4j 直连）非公共接口，版本间不保证兼容。通过 `external_metadata` 传递是 Cognee 官方支持的路径，风险更低。

## 后果

- 结构层关系通过 metadata 写入，依赖 Cognee cognify 阶段的内部实现（有黑盒风险）
- 如果 Cognee 后续版本对 metadata 的利用方式改变，需调整适配层的 metadata 编码策略
- `[[wikilinks]]` 解析由适配层负责，不同 Obsidian 用户的链接格式差异需适配层容错处理
