# SPEC: deep-obsidian

> 目标用户: Obsidian 写作爱好者
> 交付物: CLI 工具 + Python 库 + Obsidian 插件（独立项目）

---

## Problem Statement

我是一个 Obsidian 写作爱好者。我在写新笔记时，经常遇到一个问题：**"这个概念我以前肯定写过，但我记不清是哪篇了，也记不清写了什么。"**

我目前的办法是全文搜索文件名或用 grep 搜关键词。但这只能做字面匹配——如果我用"认知偏差"搜不到一篇主要讲"确认偏误"的笔记。我的笔记之间有隐含的语义关联，但 Obsidian 本身无法帮我发现它们。

我需要一个工具，在我写作时帮我回忆——不是知识管理平台，不是 RAG 系统，就是一个**写作辅助记忆工具**。

---

## Solution

一个 CLI 工具 (`deep-obsidian`)，可以做三件事：

1. **导入**：把我的 Obsidian vault 里的 Markdown 笔记灌入一个知识后端（当前用 Cognee），自动识别 wikilinks、frontmatter、tags 等 Obsidian 格式
2. **检索**：用自然语言搜索我的笔记库，返回最相关的内容片段和来源文件
3. **问答**：基于检索结果，LLM 综合生成一个回答，附带引用来源

配合一个 Obsidian 插件：**快捷键 → 发送当前光标上下文 + 问题给 CLI → 侧边栏显示回答 + 引用列表 → 点击跳转到源笔记**。

终端用户也可以直接在命令行使用 `search` 和 `query`。

---

## User Stories

### 初始化

1. As a 新用户，I want 在 vault 目录下运行 `deep-obsidian init` 就能自动创建配置，so that 我不需要手动编辑任何 JSON 文件。
2. As a 用户，I want `init` 命令可以传入 `--name` 来指定项目的逻辑名称，so that 不和文件夹名耦合。
3. As a 用户，I want init 生成的 `.deep-obsidian/settings.jsonc` 包含所有默认配置，so that 我可以按需修改而非从头写配置。

### 入库

1. As a 用户，I want 对已初始化的 vault 运行 `deep-obsidian ingest .` 就能导入所有 Markdown 文件，so that 我不需要手动逐个文件添加。
2. As a 用户，I want ingest 可以指定单个文件或子目录（`ingest path/to/note.md`），so that 我可以只导入新写的笔记。
3. As a 用户，I want ingest 默认增量更新（只处理有改动的文件），so that 我不需要每次全量重建。
4. As a 用户，I want `full` 选项可以强制全量重建，so that 当后端数据损坏时我可以重建。
5. As a 用户，I want 对未初始化的目录运行 ingest 时报错提示先 init，so that 我不会在错误的地方创建数据。
6. As a 用户，I want ingest 过程中显示实时进度，so that 我知道还要等多久。

### 检索

1. As a 用户，I want `deep-obsidian search "确认偏误"` 返回匹配的笔记文件列表和内容片段，so that 我可以快速浏览有哪些相关笔记。
2. As a 用户，I want search 的结果包含文件路径和行号，so that 我可以在 Obsidian 中定位到具体位置。
3. As a 用户，I want search 支持 `--json` 输出，so that Agent 和 Obsidian 插件可以解析结果。
4. As a 开发者，I want search 不经 LLM 加工，返回的是后端检索的原始结构化结果，so that 我可以自己决定要不要再调用 LLM。

### 问答

1. As a 用户，I want `deep-obsidian query "习惯养成有什么方法？"` 返回 LLM 综合的自然语言回答，so that 我看到的是有逻辑的回答而不是片段列表。
2. As a 用户，I want query 结果中引用来源笔记，so that 我可以追溯 AI 回答的出处。
3. As a 开发者，I want query 支持 `--json` 输出，so that Obsidian 插件可以渲染到侧边栏。
4. As a Obsidian 插件用户，I want 插件自动附加当前笔记的上下文到 query 中，so that AI 回答能结合我当前正在写的内容。

### 持续监听

1. As a 用户，I want `deep-obsidian service start` 在后台监听文件变动自动增量 ingest，so that 我不需要每次改完笔记手动跑 ingest。
2. As a 用户，I want `service status` 查看监听状态和最后处理时间，so that 我知道它在正常运行。
3. As a 用户，I want `service stop` 停止监听，so that 不占用系统资源。

### 数据管理

1. As a 用户，I want `deep-obsidian forget` 清除当前项目的所有知识库数据，so that 我可以重新开始。
2. As a 用户，I want forget 需要交互确认（`--yes` 跳过），so that 我不会误删数据。

### Obsidian 格式处理

1. As a 用户，I want 我的 `[[wikilinks]]` 被识别为文档间引用关系，so that 搜索能利用链接网络发现相关笔记。
2. As a 用户，I want frontmatter 中的 tags 被识别为笔记标签，so that 搜索时可以关联相同主题。
3. As a 用户，I want 笔记无需做任何格式修改，so that 工具开箱即用。

### 可靠性

1. As a 用户，I want 即使 LLM 服务不可用，ingest 仍能完成结构层数据导入，so that 网络问题不会阻塞我的工作流。
2. As a 开发者，I want 知识后端（当前 Cognee）是可替换的，so that 未来换 LightRAG 等方案时 CLI 接口不变。

---

## Implementation Decisions

### 项目配置机制

每个 vault 的配置存在 vault 根目录下的 `.deep-obsidian/settings.jsonc`
（JSONC 格式，支持注释；嵌套深度 ≤3 层；文件头带提示注释）：

```jsonc
{
  // 此文件含 API key，勿提交 git
  "deep-obsidian-id": "uuid-v4",
  "name": "my-blog",
  "created_at": "ISO8601",
  "last_used_at": "ISO8601",
  "cli_version": "0.1.0",

  // Cognee LLM 配置 → cognee.config.set_llm_config()
  "llm": {
    "provider": "custom",      // 可选: openai, custom, ollama...
    "model": "openai/deepseek-v4-pro",
    "api_key": "sk-xxx",
    "endpoint": "http://localhost:8317/v1"
  },

  // Cognee Embedding 配置 → cognee.config.set_embedding_config()
  "embedding": {
    "provider": "fastembed",
    "model": "BAAI/bge-small-zh-v1.5",
    "dimensions": 512
  },

  // 非 Cognee 运行时环境变量（HuggingFace 等）→ os.environ 注入
  "network": {
    "hf_endpoint": "https://hf-mirror.com",
    "hf_hub_offline": true,
    "cognee_skip_connection_test": true
  }
}
```

- `init` 创建此文件并做交互式配置引导：先问层级（项目级默认 / 用户级），
  再问 vault 路径，再问 LLM/Embedding/Network（读已有配置预填，回车继承；
  无 TTY 时 fallback 非交互）。`deep-obsidian-id` 为 UUID，文件夹改名不影响。
- **三级配置层级（ADR-0014）**：`--config`（显式）> 项目级 > 用户级
  （`~/.deep-obsidian/settings.jsonc`，必需基础层）。运行时深度 merge
  取并集，非空才覆盖。`init` 默认兼建用户级。
- `llm.*` / `embedding.*` 在触碰任何 Cognee API 前通过
  `cognee.config.set_*_config()` 注入（ADR-0012）；`network.*` 通过
  `os.environ` 设置。注入使用 merge 后的合并配置。
- 配置单一来源：`.env` 和旧的 `settings.json` 均已退役（ADR-0011）。

**存储布局（ADR-0014）：**

- Cognee 数据 `.cognee/` 始终在 vault 目录下（`<vault>/.cognee/`）——删 vault
  即删数据，隔离完整。
- 项目级状态：`.deep-obsidian/vault/hashes.json`（一个项目 = 一个 vault）。
- 用户级状态：`~/.deep-obsidian/vaults/<hash>/hashes.json`，映射记录在
  `~/.deep-obsidian/vaults/index.json`。
- hashes 内文件路径相对 vault 目录。
- `vaults` 子命令组：`vaults list` 列映射，`vaults relink <旧> <新>` 重关联
  （vault 目录移动后 hash 失配时使用）。
- 所有命令支持全局 `--config <file>`（显式指定 settings.jsonc）；
  `search/query/forget/status` 的 `--dir` 已改名为 `--vault`。

### 安装流程（install.sh）

```bash
git clone <repo-url> && cd deep-obsidian
./install.sh        # 环境检测 → 缺依赖给命令让用户确认 → uv sync → 验证
```

- `install.sh` 只管环境与依赖（Python 3.11+ / uv / git），缺什么给明确命令
  让用户确认后执行，不静默安装。
- 幂等：`.venv/` 已存在则修复式刷新，`--reset` 删 `.venv/` 重建（ADR-0013）。
- 可观测：全程日志写 `logs/install.log`；`--check` 只跑环境检测输出 JSON。
- 配置引导不在此处——那是 `deep-obsidian init` 的职责。

### CLI 命令扁平化

不使用子命令层级（如 `deep-obsidian vault ingest`），所有命令在顶层：

- `init` — 项目初始化
- `ingest` — 导入知识
- `search` — 结构化检索
- `query` — LLM 问答
- `service` — 持续监听（子命令: start/status/stop）
- `forget` — 清除数据

### search vs query 的语义区分

- `search`：调用后端的检索接口，返回结构化数据（文档片段、节点、边、来源路径）。**不经 LLM 加工**。输出默认为人类可读文本，`--json` 为机器可读。供 Agent 和程序消费。
- `query`：内部调用 search → 将检索结果 + 用户问题发送给 LLM → 返回综合的自然语言回答 + 引用列表。**供人类直接阅读**。

### 模块架构

- **设置模块**（改造）：`read_settings(path)` 向上查找并解析 settings.jsonc；`init_project(path, name)` 创建项目。
- **公共 API**（修改）：`ingest(target, ...)` / `search(query, ...)` / `query(question, ...)` / `forget()`。每个函数接收一个 settings dict 或 path，自行调用设置模块。
- **CLI**（重写）：每个命令解析参数 → 调用设置模块查找项目 → 调用公共 API → 格式化输出。
- **抽取器**（不变）：wikilinks / frontmatter / tags 的纯函数提取。
- **知识后端**（适配层）：当前为 Cognee，由一个薄适配层封装。

### 后端可替换性

当前后端为 Cognee，公共 API 不直接暴露 Cognee 概念。未来替换后端的步骤：

1. 新增 `backend/lightrag.py`，实现与当前适配层相同的接口
2. 替换适配层中的 Cognee 调用，配置注入改为对应后端的 setter
3. CLI 和公共 API 无需修改

### LLM 降级

ingest 过程中如果 LLM 不可用（超时/503/API key 问题），结构层数据（wikilinks, tags, frontmatter）仍然写入，语义层（LLM 推理）标记为待处理。用户得到警告但不中断。

---

## Testing Decisions

### 测试分层

```
┌─ CLI 测试 (CliRunner)              ─┐  验证: 参数解析、输出格式、错误提示
├─ 公共 API 测试                      ─┤  验证: ingest/search/query/forget 逻辑
├─ 设置模块测试 (新增)                 ─┤  验证: init / read / find_project_root
├─ 抽取器测试 (已有 33 个, 不变)      ─┤  验证: wikilinks / frontmatter / tags
└─ 后端适配层测试 (mock Cognee)      ─┘  验证: 数据转换、容错、降级
```

### 测试原则

- 只测试外部行为，不测试实现细节
- 单元测试不依赖 Cognee（毫秒级）
- 集成测试用 mock LLM
- CLI 测试用 Click 的 CliRunner
- install.sh 用 bats-core 做 shell 单元测试（分支逻辑：检测/缺依赖/幂等），
  e2e 测试 mock 下载等外部环境（见下）

### install.sh 测试

- **bats-core 单元测试**（`tests/bats/`）：测 `--check` 检测逻辑、缺依赖分支、
  幂等性（重复执行不重建）。mock `uv` / `brew` / `python3` 等外部命令。
- **e2e 测试**（`tests/e2e/`）：mock 外部下载（uv 安装、Python 安装）后跑
  完整流程，断言 `install.sh --check` 的 JSON 输出结构与关键字段。
- `install.sh --check` 是测试与排障的稳定接口（ADR-0013）。

### 已有的测试资产

- `tests/unit/test_wikilinks.py` — 12 个，保持不变
- `tests/unit/test_frontmatter.py` — 10 个，保持不变
- `tests/unit/test_tags.py` — 11 个，保持不变
- `tests/unit/test_scanner.py` — 9 个，保持不变
- `tests/unit/test_progress.py` — 7 个，保持不变
- `tests/unit/test_health.py` — 5 个，保持不变
- `tests/integration/test_ingest.py` — 6 个，需重构为通过公共 API + mock settings
- `tests/integration/test_search.py` — 3 个，需重构
- `tests/integration/test_filters.py` — 3 个，需重构

---

## Out of Scope

- Obsidian 插件（独立项目）
- LightRAG 后端实现（当前版本只用 Cognee）
- 多 vault 同时查询
- 图表可视化
- Web UI
- 图片内容提取

---

## Further Notes

- 日志默认输出到 `~/.deep-obsidian/log/`，默认静默，`--debug` 开启。
- Cognee 的数据文件存 vault 内的 `.cognee/`，deep-obsidian 的配置存 `.deep-obsidian/`，两者在 vault 内平行不互扰。
