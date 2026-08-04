# deep-obsidian

> 将 Obsidian（或任意 Markdown）知识库一键转化为可语义查询的知识图谱。

一行命令，把你的笔记变成 LLM 能理解、能搜索、能关联的知识网络。

---

## 前置条件

- **Python 3.11+**
- **uv**（推荐）或 pip
- **LLM 服务**：Cognee 依赖 LLM 做语义推理。你需要一个 OpenAI 兼容的 API（或已配置好的本地模型）

### 配置 LLM

Cognee 通过环境变量识别 LLM。以 DeepSeek 代理为例：

```bash
export LLM_PROVIDER="openai"
export LLM_API_KEY="your-api-key"
export LLM_ENDPOINT="https://your-proxy/v1"
export LLM_MODEL="deepseek-chat"
```

更多配置见 [用户操作手册](docs/USER_GUIDE.md#llm-配置)。

---

## 安装

### 方式一：uv（推荐）

```bash
git clone <repo-url> && cd deep-obsidian
uv sync --dev

# 验证
uv run deep-obsidian --help
```

> CLI 通过 `uv run` 运行。如果想直接用 `deep-obsidian`：
>
> ```bash
> source .venv/bin/activate   # 激活虚拟环境
> deep-obsidian --help      # 此后可直接运行
> ```

### 方式二：pip + venv

```bash
git clone <repo-url> && cd deep-obsidian
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .

# 验证
deep-obsidian --help
```

---

## 快速开始

```bash
# 1. 初始化项目
uv run deep-obsidian init ~/my-obsidian-vault

# 2. 导入你的笔记库
uv run deep-obsidian ingest ~/my-obsidian-vault --dataset my-blog

# 3. 语义搜索
uv run deep-obsidian search "养成习惯有什么方法" --dataset my-blog

# 4. 清理知识库
uv run deep-obsidian forget --yes
```

---

## CLI 命令参考

| 命令 | 说明 |
|------|------|
| `uv run deep-obsidian init <path>` | 初始化项目 |
| `uv run deep-obsidian ingest <path>` | 导入 vault 所有 .md 文件 |
| `ingest <path> --full` | 强制全量重建（忽略增量指纹） |
| `uv run deep-obsidian search <query>` | 语义搜索 |
| `search <query> --json` | JSON 输出（给脚本/TS 消费） |
| `search <query> --tag habit` | 按标签过滤 |
| `uv run deep-obsidian query <question>` | LLM 问答（含引用来源） |
| `uv run deep-obsidian forget` | 删除知识库（交互确认） |
| `forget --yes` | 跳过确认 |

### ingest 选项

| 选项 | 默认 | 说明 |
|------|------|------|
| `--dataset`, `-d` | 目录名 | 知识库槽位名 |
| `--full` | false | 忽略增量，全量重灌 |
| `--json` | false | JSON 格式输出进度 |

### search 选项

| 选项 | 默认 | 说明 |
|------|------|------|
| `--dataset`, `-d` | — | 搜索哪个知识库 |
| `--top-k` | 5 | 返回结果数 |
| `--json` | false | JSON 输出 |
| `--tag` | — | 按 tag 过滤 |
| `--linked-to` | — | 查哪些笔记链接到指定笔记 |
| `--linked-from` | — | 查指定笔记链接到哪些笔记 |

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

# 入库
result = await ingest("~/my-blog", dataset="my-blog")
# => {"total": 74, "success": 72, "failed": 2, ...}

# 搜索
items = await search("习惯", dataset="my-blog", top_k=5)
# => [{"label": "习惯", "content": "...", "layer": "semantic"}, ...]

# 状态
info = await status("my-blog")

# 清理
await forget("my-blog")
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
