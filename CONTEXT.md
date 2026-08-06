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

入库分两个阶段：

1. **Add** — 将原文和元数据写入 Dataset，Cognee 返回 data_id
2. **Cognify** — LLM 分析文本内容，构建语义层图

批量新增时两阶段分离（积攒后批量 cognify 以控制 LLM 消耗），单文件修改时合为一步（update 自带 cognify）。

### Sync（同步）

将持续监听文件变更（新增、修改、删除）并自动触发增量入库的后台过程。Sync 由 Service 驱动，不等同于用户手动执行 `ingest`。

### Search（检索）

从知识图谱中检索与查询相关的内容，返回**结构化原始数据**（文档片段、节点、边、来源路径）。不经 LLM 加工。供 Agent 和程序消费。

### Query（问答）

基于检索结果，由 LLM 综合生成**自然语言回答**。供人类用户直接阅读。内部流程 = Search 检索 → LLM 合成。

### Forget（遗忘）

从知识图谱中删除数据，行为类似 ``rm``。

- **文件/目录级**：``forget Books/Justice.md`` 按路径删除；``forget Books/`` 删除目录下所有已索引文件。支持相对路径、绝对路径、文件名（不含目录）模糊匹配。
- **全量**：``forget --all`` 清空整个 dataset。与 targets 互斥。
- **确认**：单文件不确认；多文件（2+）列文件清单后确认；``--all`` 醒目警告后确认。``-y/--yes`` 跳过所有确认。
- **副作用**：同步清理 ``hashes.json`` 中的对应条目，下次 ``ingest`` 会重新入库。

### Service（后台服务）

常驻后台进程，负责文件监控和自动同步。生命周期：

- `service start` — 启动守护进程
- `service stop` — 优雅关闭
- `service status` — 查询运行状态

Service 不随 CLI 命令自动启动（显式启停模型）。

---

## 文件变更模型

### File Event（文件事件）

文件监控产生的事件，经去重和防抖后分类为三种：

- **Created** — 新文件（Vault 中有，hashes.json 中无）
- **Modified** — 内容已变（哈希不匹配）
- **Deleted** — 文件已删除（hashes.json 中有，Vault 中无）

所有文件哈希比较基于 SHA-256 前 16 位。

### Debounce（防抖）

编辑器保存文件时可能触发 4-12 个 OS 文件事件（write、rename、tmp file、metadata flush），防抖将这些高频事件合并为一个有效事件。采用动态防抖策略——等待文件系统事件流"安静"下来后再处理。

### Polling Fallback（轮询兜底）

OS 文件事件可能丢失（macOS FSEvents 延迟、inotify 队列溢出）。每 30 秒对 Vault 全量扫描一次，对比 hashes.json 找出遗漏的变更，作为事件监控的兜底机制。

### 批量 cognify

新增文件先全部 add() 入 Dataset 并缓存 data_id，积攒后在 Phase 2 对该 dataset 发起一次 `cognee.cognify()` 调用，而不是逐文件调用 LLM，用来控制 LLM 消耗。目前是单一批次调用，没有并发控制/任务池化调度（若未来需要并发限流可再引入）。

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
| 文件指纹 + data_id | 适配层 | `.deep-obsidian/hashes.json`（扩展了 data_id 字段） |
| Cognee 数据项 data_id | Cognee add() 返回 | `.deep-obsidian/hashes.json`（适配层缓存） |

---

## 接口

### CLI

| 命令 | 语义 |
|------|------|
| `deep-obsidian init <path>` | 初始化项目 |
| `deep-obsidian ingest <vault>` | 全量/增量入库（手动触发） |
| `deep-obsidian service start` | 启动文件监控后台服务 |
| `deep-obsidian service stop` | 停止后台服务 |
| `deep-obsidian service status` | 查看服务状态 |
| `deep-obsidian search <query>` | 结构化检索（无 LLM 加工） |
| `deep-obsidian query <question>` | LLM 问答（检索 + 综合回答） |
| `deep-obsidian forget <targets...>` | 遗忘指定文件/目录（需指定目标或用 ``--all``） |

### Python API

```python
from deep_obsidian import ingest, search, status, forget
```
