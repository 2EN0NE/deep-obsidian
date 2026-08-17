# deep-obsidian 领域术语

> 本文档记录项目的通用语言（Ubiquitous Language），不含实现细节。

---

## 核心概念

### Vault（工作空间）

deep-obsidian **识别和管理的工作空间**——用户存放 Markdown 笔记（含 Obsidian，但不限于）的根目录。包含 `.md` 文件、子目录、`.obsidian/` 配置（若有）。Vault 是适配层的输入；deep-obsidian 本身不依赖 Obsidian 存在即可运行，故术语上以「工作空间」为准，日常使用中与 Obsidian 的「笔记根目录」概念统一。

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

### Ingest 运行态（Idle / Running / Stale）

某次 `ingest` 是否正在进行、进行到哪一步的可观测状态，供 `status` 命令查询。三态：**Idle**（当前没有 ingest 在跑）、**Running**（正在跑，可知道所处阶段和进度）、**Stale**（上一次 ingest 异常终止，留下了未清理的运行态记录）。跟 Service 的运行状态是两个独立概念——Ingest 运行态描述的是「一次入库任务」，Service 状态描述的是「文件监控常驻进程」本身。

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
| 文件指纹 + data_id | 适配层 | `hashes.json`（扩展了 data_id 字段） |
| Cognee 数据项 data_id | Cognee add() 返回 | `hashes.json`（适配层缓存） |

**存储布局（ADR-0014）：**

- Cognee 数据目录 `.cognee/` **始终在 vault 目录下**（`<vault>/.cognee/`）——删 vault 即删数据，隔离完整。
- 项目级状态（hashes.json）：`.deep-obsidian/vault/hashes.json`（一个项目 = 一个 vault，直接存放）。
- 用户级状态：`~/.deep-obsidian/vaults/<hash>/hashes.json`，其中 `<hash>` 是 vault 目录绝对路径的哈希；映射关系记录在 `~/.deep-obsidian/vaults/index.json`。
- hashes.json 内的文件路径**相对 vault 目录**，不相对配置目录。

## 配置层级

配置来自三个层级，运行时按优先级 **深度 merge 取并集**，冲突时以最个性化的为准：

```text
--config（显式指定） > 项目级（.deep-obsidian/settings.jsonc） > 用户级（~/.deep-obsidian/settings.jsonc）
```

- **深度 merge**：嵌套键逐键合并（如 llm.provider 用项目级、llm.api_key 项目级为空则继承用户级）。
- **非空才覆盖**：高优先级非空（非 null/""/缺失）才覆盖低优先级——项目级 api_key 留空即继承用户级 key。
- 用户级配置是**必需基础层**（完整配置，含 name），`init` 默认兼建用户级；merge 时若用户级缺失则报错提示。
- 配置目录（.deep-obsidian/）仅存配置与状态文件；`.cognee/` 数据始终跟 vault 走。

## 安装与配置

### Install（安装）

把代码和环境装到「能执行 `deep-obsidian`」状态的过程，由 `install.sh` 负责。幂等——重复执行只做修复式刷新（`uv sync`），`--reset` 才删 `.venv/` 重建。不做配置引导，那是 Init 的事。

### Init（初始化）

在 vault 下创建项目配置并做交互式配置引导的过程，由 `deep-obsidian init` 命令负责。写 `settings.jsonc`、提示后续使用路径。与 Install 是两回事——Install 管环境，Init 管配置。

### settings.jsonc（项目配置）

项目唯一配置来源，存于 `.deep-obsidian/settings.jsonc`。JSONC 格式（支持注释），嵌套深度 ≤3 层，文件头带「含 API key 勿提交 git」提示。取代了过去的 `.env` 和 `settings.json`（ADR-0011）。

### 配置注入（Config Injection）

从 settings.jsonc 读取 LLM/Embedding 配置后，通过 `cognee.config.set_llm_config()` / `set_embedding_config()` 写入 Cognee 的过程（ADR-0012）。不依赖环境变量，用户关终端配置不丢。

## 接口

### CLI

| 命令 | 语义 |
|------|------|
| `deep-obsidian init <path>` | 初始化项目 |
| `deep-obsidian ingest <vault>` | 全量/增量入库（手动触发） |
| `deep-obsidian status` | 查看 ingest 运行状态（idle / running / stale） |
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
