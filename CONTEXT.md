# deep-obsidian 领域术语

> 本文档记录项目的通用语言（Ubiquitous Language），不含实现细节。

---

## 核心概念

### Vault（知识库目录）

用户的 Obsidian（或任意 Markdown）笔记根目录。包含 `.md` 文件、子目录、`.obsidian/` 配置。Vault 是适配层的输入。

### Dataset（槽位）

Cognee 内部知识库单元。一个 Dataset 对应一个独立的图数据库和向量索引，数据集之间互不可见查询。槽位名由用户指定或从 Vault 目录名自动生成。

### Ingest（入库）

将 Vault 中的 Markdown 文件转换为 Cognee 可查询的知识图谱的过程。全称 Ingestion Pipeline。

### Search（检索）

从知识图谱中检索与查询相关的内容，返回**结构化原始数据**（文档片段、节点、边、来源路径）。不经 LLM 加工。供 Agent 和程序消费。

### Query（问答）

基于检索结果，由 LLM 综合生成**自然语言回答**。供人类用户直接阅读。内部流程 = Search 检索 → LLM 合成。

### Forget（遗忘）

按 Dataset 粒度删除整个知识图谱，或按单篇文件粒度删除其所有关联节点和边。

---

## 图结构概念

### 结构层图（Structural Graph）

从 Markdown 格式中**脚本化提取**的关系：

- `[[wikilinks]]` → 文档间引用边
- Frontmatter `tags:` → 标签归属
- Frontmatter YAML 键值对 → 节点属性

结构层图**不经过 LLM**，由适配层代码直接构造。

### 语义层图（Semantic Graph）

Cognee `cognify` 阶段由 LLM 分析文本内容生成的节点和边。包括实体识别、关系推理、主题聚类等。

### 统一知识域（Unified Knowledge Domain）

最终查询时，结构层图和语义层图合并为一个图。用户看到的是「自己组织的结构 + AI 发现的关联」。

---

## 数据边界

| 概念 | 谁负责 | 存哪里 |
|------|--------|--------|
| Markdown 原文 | 用户 | Vault 内 |
| 结构层图（wikilinks, 属性） | 适配层 | `external_metadata` 传递给 Cognee |
| 语义层图（LLM 推理） | Cognee cognify | `.cognee/` 下 Ladybug + SQLite |
| 向量索引 | Cognee | `.cognee/` 下 |
| 文件指纹（mtime/hash） | 适配层 | `.deep-obsidian/` 下（不跟 Cognee 混） |

---

## 接口

### CLI

| 命令 | 语义 |
|------|------|
| `deep-obsidian init <path>` | 初始化项目 |
| `deep-obsidian ingest <vault>` | 全量/增量入库 |
| `deep-obsidian search <query>` | 结构化检索（无 LLM 加工） |
| `deep-obsidian query <question>` | LLM 问答（检索 + 综合回答） |
| `deep-obsidian forget` | 删除知识库 |

### Python API

```python
from deep_obsidian import ingest, search, status, forget
```
