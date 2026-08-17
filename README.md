# deep-obsidian

> 将 Obsidian（或任意 Markdown）知识库一键转化为可语义查询的知识图谱。

一行命令，把你的笔记变成 LLM 能理解、能搜索、能关联的知识网络。

---

## 前置条件

- **Python 3.11+**（安装脚本会自动检测）
- **uv**（包管理器，安装脚本会自动引导）
- **git**
- **LLM 服务**：Cognee 依赖 LLM 做语义推理。你需要一个 OpenAI 兼容的 API（或已配置好的本地模型）

---

## 安装

### 方式一：install.sh（推荐，小白友好）

```bash
git clone <repo-url> && cd deep-obsidian
./install.sh
```

脚本会自动：检测环境（Python 3.11+ / uv / git）→ 缺什么给出明确命令让你确认后执行 →
`uv sync`（不装开发依赖）→ 验证 CLI 可用。全程日志写 `logs/install.log`。

常用参数：

```bash
./install.sh --check   # 只检测环境，输出 JSON（排障用）
./install.sh --reset   # 删除 .venv/ 重新安装
./install.sh --help    # 帮助
```

装完后激活环境：

```bash
source .venv/bin/activate
```

### 方式二：手动 uv

```bash
git clone <repo-url> && cd deep-obsidian
uv sync

# 验证
source .venv/bin/activate
deep-obsidian --help
```

---

## 配置 LLM（初始化引导）

安装完成后运行 `deep-obsidian init`，交互式引导你配置 LLM / Embedding / 网络参数，
写入项目唯一的配置文件 `.deep-obsidian/settings.jsonc`（JSONC 格式，带注释说明）。

```bash
deep-obsidian init ~/my-obsidian-vault
```

- 直接回车 = 保留当前值 / 使用默认值
- 配置存于 `.deep-obsidian/settings.jsonc`（含 API key，**勿提交 git**，已在 .gitignore）
- 想改配置：重新运行 `deep-obsidian init` 或直接编辑该文件

更多配置见 [用户操作手册](docs/USER_GUIDE.md#llm-配置)。

---

## 快速开始

> 以下命令假设你已激活虚拟环境（`source .venv/bin/activate`）或通过
> pip 安装。如果还在用 `uv run`，把所有 `deep-obsidian` 替换为
> `uv run deep-obsidian`。

```bash
# 1. 初始化项目
deep-obsidian init ~/my-obsidian-vault

# 如果之前运行过，用 --force 重置到干净状态：
deep-obsidian init ~/my-obsidian-vault --force

# 2. 导入你的笔记库
deep-obsidian ingest ~/my-obsidian-vault

# 3. 语义搜索（--vault 指向同一个 vault，数据集名自动从 settings.jsonc 读取）
deep-obsidian search "养成习惯有什么方法" --vault ~/my-obsidian-vault

# 4. 清理知识库
deep-obsidian forget --all -y
```

---

## CLI 命令参考

<!-- CLI-REF-START -->

### 通用约定

所有命令都遵守以下规约：

- **`--help`** — 每个命令和子命令都支持 `--help`，显示完整用法和所有可用选项。

- **`--config <file>`** — 全局选项，直接指定 settings.jsonc 路径（覆盖项目级/用户级自动查找）。所有命令均可携带。

- **`--json`** — 支持 JSON 输出的命令（`ingest`、`search`、`query`、`forget`、`status`）统一使用 `--json` 标志，输出单行机器可读 JSON。

- **`--vault <path>`** — 需要指定 vault 目录的命令（`search`、`query`、`forget`、`status`）统一使用 `--vault`。默认从当前目录向上查找包含 `.deep-obsidian/settings.jsonc` 的目录。

- **位置参数** — `init` 和 `ingest` 的 vault 路径是位置参数（不是 `--vault`），因为它们是初始化或导入操作，天然需要一个明确的路径。

### 命令参考

### `init`

初始化 deep-obsidian 项目。

**参数：**

- `PATH` （可选）

| 选项 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `-n`, `--name` | TEXT | — | Project name (default: directory name) |
| `-f`, `--force` | flag | false | Reset: delete stale .deep-obsidian/ and .cognee/ before init（注意：用户级 --force 会删除整个 ~/.deep-obsidian/） |

### `ingest`

将 Markdown 文件导入知识图谱。

**参数：**

- `TARGET`

| 选项 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--full` | flag | false | Force full re-ingest |
| `--json` | flag | false | Machine-readable output |

### `search`

检索知识图谱（不经 LLM 加工）。

**参数：**

- `QUERY`

| 选项 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--vault` | PATH | — | Vault directory to search (default: current directory or an ancestor) |
| `--top-k` | INT | 5 | Number of results |
| `--tag` | TEXT | — | Filter by tag |
| `--linked-to` | TEXT | — | Filter: notes that link TO this note |
| `--linked-from` | TEXT | — | Filter: notes linked FROM this note |
| `--date-from` | TEXT | — | Filter: notes dated on or after YYYY-MM-DD |
| `--date-to` | TEXT | — | Filter: notes dated on or before YYYY-MM-DD |
| `--source` | TEXT | — | Filter by source file path |
| `--json` | flag | false | Machine-readable output |

### `query`

提问并获得 AI 合成的答案（含引用来源）。

**参数：**

- `QUESTION`

| 选项 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--vault` | PATH | — | Vault directory to query (default: current directory or an ancestor) |
| `--top-k` | INT | 5 | Number of search results to use |
| `--json` | flag | false | Machine-readable output |

### `forget`

从知识图谱中删除已索引的文件。

**参数：**

- `TARGETS` （可选）

| 选项 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--all` | flag | false | Clear the entire dataset |
| `--vault` | PATH | — | Vault directory (default: current directory or an ancestor) |
| `-y`, `--yes` | flag | false | Skip confirmation |
| `--json` | flag | false | Machine-readable output |

### `status`

查看当前是否有 ingest 正在运行。

| 选项 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--vault` | PATH | — | Vault directory (default: current directory or an ancestor) |
| `--json` | flag | false | Machine-readable output |

### `vaults list`

列出用户级注册的 vault 映射。

### `vaults relink`

重新关联已移动路径的 vault。

**参数：**

- `OLD_PATH`
- `NEW_PATH`

### `service start`

启动文件变更监控。

### `service status`

查看文件监控守护进程是否存活。

### `service stop`

停止文件监控服务。

<!-- CLI-REF-END -->

---

## 开发与测试

依赖安装：

```bash
uv sync --dev
```

测试按交付形态分四层，目录即分层（与 CI 的 lint/test/integration/e2e/shell job 对应）：

```bash
# 开发时最快反馈：单元测试——零 Cognee 依赖、毫秒级（实测 ~4s）
uv run pytest tests/unit/

# 集成测试——真实 Cognee + mock LLM（不产生真实 LLM 调用）
ENABLE_BACKEND_ACCESS_CONTROL=false COGNEE_SKIP_CONNECTION_TEST=true \
  uv run pytest tests/integration/

# e2e——CLI 全链路（CliRunner + 子进程 + mock LLM）
ENABLE_BACKEND_ACCESS_CONTROL=false COGNEE_SKIP_CONNECTION_TEST=true \
  uv run pytest tests/e2e/

# install.sh 分支逻辑（需先安装 bats-core）
bats tests/bats/

# 一条命令跑全部 Python 测试
uv run pytest
```

提交前 pre-commit 会自动跑 ruff + 单元测试。架构红线守卫脚本（CI lint job 同款）：

```bash
./scripts/check_extractors_isolation.sh   # 核心红线③：extractors/ 零 Cognee 依赖
./scripts/check_cognee_config.sh          # 核心红线④：cognee.config 函数调用 + data/system 双设
./scripts/check_cognee_graph_api.sh       # 核心红线①：不直接操作 Cognee 内部图 API
```

---

## 调试与日志

CLI 默认干净输出，Cognee 的导入日志被自动抑制。排查问题时开启调试模式：

```bash
# 查看 Cognee 详细日志（包括 API 调用、数据库操作）
DEEP_OBSIDIAN_DEBUG=1 deep-obsidian search "测试"

# 仅查看 WARNING 以上
LOG_LEVEL=WARNING deep-obsidian search "测试"
```

Cognee 完整日志同时写入 `~/.cognee/logs/`，无论控制台是否静默。详细文档见 [日志体系](docs/LOGGING.md)。

---

## Python API

```python
from deep_obsidian import ingest, search, status, forget

# 入库（dataset 名总是该 vault 的 settings.jsonc 里的 name）
result = await ingest("~/my-blog")
# => {"total": 74, "added": 50, "modified": 20, "deleted": 2, ...}

# 搜索（vault_path 指定要找哪个 vault，默认当前目录向上查找）
items = await search("习惯", vault_path="~/my-blog", top_k=5)
# => [{"label": "《掌控习惯》", "content": "...", "source_file": "Books/《掌控习惯》.md", "match_type": "vector"}, ...]

# 状态
info = await status("my-blog")

# 清理
await forget(all=True, vault_path="~/my-blog")
await forget(["Books/Justice.md"], vault_path="~/my-blog")
```

---

## 常见问题

### ingest 很慢

每篇笔记约 2 分钟（取决于 LLM 响应速度）。74 篇约 2.5 小时。支持断点续跑——中断后重新 `ingest` 会跳过已完成文件。

### LLM 不可用

如果 LLM 挂了，`ingest` 仍会继续处理其他文件，失败的文件会输出警告。结构层数据（wikilinks、标签）不依赖 LLM，始终可用。

### 数据存在哪

所有 Cognee 数据存在 vault 的 `.cognee/` 目录下，跟你笔记一起。`.deep-obsidian/` 存进度和文件指纹。

---

## 文档

| 文档 | 面向 |
|------|------|
| [用户操作手册](docs/USER_GUIDE.md) | 用户 |
| [领域术语](CONTEXT.md) | 开发者 |
| [架构设计](docs/SPEC.md) | 开发者 |
| [架构决策](docs/adr/) | 开发者 |
| [日志体系](docs/LOGGING.md) | 开发者
