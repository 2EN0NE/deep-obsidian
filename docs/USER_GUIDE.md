# deep-obsidian 用户操作手册

> 从零开始，把一个 Markdown 知识库变成可语义搜索的知识图谱。

---

## 目录

1. [环境准备](#环境准备)
2. [LLM 配置](#llm-配置)
3. [入库：第一次 ingest](#入库第一次-ingest)
4. [搜索：语义召回](#搜索语义召回)
5. [增量更新](#增量更新)
6. [槽位管理](#槽位管理)
7. [JSON 输出（给脚本用）](#json-输出给脚本用)
8. [Obsidian 插件集成](#obsidian-插件集成)
9. [故障排查](#故障排查)

---

## 环境准备

### 1. 安装 Python 3.11+

```bash
python3 --version  # 必须 ≥ 3.11
```

### 2. 安装 uv（推荐）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

或 pip：

```bash
pip install uv
```

### 3. 克隆并安装项目

```bash
git clone <repo-url>
cd deep-obsidian
uv sync --dev
```

### 4. 验证

```bash
uv run deep-obsidian --help
# 应显示命令列表
```

---

## LLM 配置

Cognee 需要 LLM 服务才能进行语义推理（cognify 阶段）。适配层本身不管理 LLM 配置——由 Cognee 的环境变量接管。

### 通用格式

```bash
export LLM_PROVIDER="openai"
export LLM_API_KEY="sk-xxxx"
export LLM_ENDPOINT="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o-mini"
```

### DeepSeek 代理示例

```bash
export LLM_PROVIDER="openai"
export LLM_API_KEY="your-deepseek-key"
export LLM_ENDPOINT="https://api.deepseek.com/v1"
export LLM_MODEL="deepseek-chat"
```

### 本地 Ollama

```bash
export LLM_PROVIDER="ollama"
export LLM_MODEL="llama3.1"
```

### Embedding 模型

Cognee 默认用 `BAAI/bge-small-zh-v1.5`（中文友好）。首次运行会自动下载（~100MB）。

如需离线使用：

```bash
export HF_HUB_OFFLINE=1
```

### Cognee 必需的环境变量

```bash
# 关闭多用户权限（单机使用必须）
export ENABLE_BACKEND_ACCESS_CONTROL=false
# 跳过连接测试（加速启动）
export COGNEE_SKIP_CONNECTION_TEST=true
```

---

## 入库：第一次 ingest

### 准备 Vault

你的 Obsidian vault 就是一个普通文件夹。任何包含 `.md` 文件的目录都可以。

```
my-blog/
├── Books/
│   ├── 《原子习惯》.md
│   └── 《系统之美》.md
├── Daily/
│   ├── 2024-01-01.md
│   └── 2024-01-02.md
└── 欢迎.md
```

适配层会自动：

- 跳过 `.obsidian/`、`.trash/` 等隐藏目录
- 跳过 `attachments/` 目录（不处理图片）
- 提取 frontmatter（`tags`、`aliases`、自定义属性）
- 解析 `[[wikilinks]]` 作为文档间关系

### 执行入库

```bash
ENABLE_BACKEND_ACCESS_CONTROL=false \
COGNEE_SKIP_CONNECTION_TEST=true \
deep-obsidian ingest ~/my-blog --dataset my-blog
```

### 预计耗时

| 笔记数量 | 预计耗时 |
|----------|---------|
| 5 篇 | ~10 分钟 |
| 50 篇 | ~1.5 小时 |
| 200 篇 | ~6 小时 |

> 每篇约 2 分钟，瓶颈在 LLM 推理速度。

### 进度与断点续跑

入库中途中断（Ctrl+C）不会丢失已完成的工作。重新执行相同命令即可从断点继续。

```bash
# 查看当前进度
deep-obsidian status --dataset my-blog
```

进度文件存在项目根目录的 `.cognee-obsidian/progress.json`，哈希存在 `.deep-obsidian/hashes.json`。

### 数据存储位置

```
my-blog/
├── .cognee/              ← Cognee 图数据库 + 向量索引
│   └── databases/
│       ├── cognee_graph_ladybug/
│       └── ...
├── .deep-obsidian/       ← 适配层文件指纹
│   └── hashes.json
├── .cognee-obsidian/     ← 适配层进度
│   └── progress.json
└── Books/
    └── ...
```

删除项目根目录下的 `.cognee/`、`.deep-obsidian/` 和 `.cognee-obsidian/` 即可完全清除本地数据。

---

## 搜索：语义召回

### 基础搜索

```bash
deep-obsidian search "养成习惯有什么方法" --dataset my-blog
```

输出：

```
[1] 习惯 (semantic): 从经验中学到的心理捷径，过去为解决问题而采取的步骤的记忆。
[2] 培养良好习惯的四步法 (semantic): 养成习惯的过程分为提示、渴求、反应和奖励四个步骤。
```

每行标注了 `layer`：

- **semantic**：来自 LLM 语义推理的关联
- **structural**：来自 wikilinks/tags 的结构关联

### 按标签过滤

```bash
deep-obsidian search "学习" --dataset my-blog --tag habit
```

只返回带 `#habit` 标签的笔记中与"学习"相关的内容。

### 按 wikilink 关系过滤

```bash
# 哪些笔记链接到了《原子习惯》？(入链)
deep-obsidian search "习惯" --dataset my-blog --linked-from "原子习惯"

# 《原子习惯》链接到了哪些笔记？(出链)
deep-obsidian search "" --dataset my-blog --linked-to "原子习惯"
```

### 调整返回数量

```bash
deep-obsidian search "习惯" --top-k 10
```

---

## 增量更新

当你修改、新增或删除笔记后，重新运行 ingest 会自动检测变化：

```bash
# 第一次：全量入库
deep-obsidian ingest ~/my-blog --dataset my-blog

# 修改一篇笔记后：
deep-obsidian ingest ~/my-blog --dataset my-blog
# → 只处理变化的文件，其余跳过
```

工作原理：适配层在 `.deep-obsidian/hashes.json` 中记录每篇笔记的 SHA-256 哈希。每次 ingest 对比哈希值，只处理变化的文件。

### 强制全量重建

```bash
deep-obsidian ingest ~/my-blog --dataset my-blog --full
```

---

## 槽位管理

你可以为不同的 vault 创建独立的槽位（dataset），它们互不可见。

```bash
# 工作笔记
deep-obsidian ingest ~/work-vault --dataset work

# 个人博客
deep-obsidian ingest ~/blog-vault --dataset blog

# 搜索只在指定槽位内
deep-obsidian search "KPI" --dataset work
deep-obsidian search "旅行" --dataset blog
```

### 查看槽位状态

```bash
deep-obsidian status --dataset work
```

### 删除槽位

```bash
# 交互确认
deep-obsidian forget

# 跳过确认
deep-obsidian forget --yes
```

---

## JSON 输出（给脚本用）

所有命令都支持 `--json` 参数，输出机器可读的 JSON。

### 搜索

```bash
deep-obsidian search "习惯" --dataset my-blog --json
```

```json
[
  {
    "label": "习惯",
    "content": "从经验中学到的心理捷径...",
    "source_file": "graph",
    "kind": "graph_completion",
    "layer": "semantic"
  }
]
```

### 入库进度

```bash
deep-obsidian ingest ~/my-blog --dataset my-blog --json
```

```json
{"total": 50, "success": 42, "failed": 1, "skipped": 7, "warnings": [...], "elapsed_seconds": 1234.5}
```

### TypeScript 集成示例

```typescript
const { stdout } = await exec(
  "deep-obsidian search 'habit' --dataset my-blog --json"
);
const results = JSON.parse(stdout);
// => [{ label: "习惯", content: "...", layer: "semantic" }, ...]
```

---

## Obsidian 插件集成

适配层设计为一个可被 Obsidian 插件调用的 CLI 工具。典型的集成方式：

```
┌─────────────────┐     JSON stdout      ┌──────────────────┐
│  Obsidian 插件   │ ──────────────────→ │  deep-obsidian    │
│  (TypeScript)   │ ←────────────────── │  (Python CLI)     │
└─────────────────┘     child_process    └──────────────────┘
```

插件通过 `child_process.exec` 调用 CLI，`--json` 获取结构化输出：

```typescript
// obsidian-plugin/src/cognee.ts
import { exec } from "child_process";

export async function search(query: string, dataset: string) {
  return new Promise((resolve, reject) => {
    exec(
      `deep-obsidian search "${query}" --dataset ${dataset} --json`,
      (err, stdout) => {
        if (err) return reject(err);
        resolve(JSON.parse(stdout));
      }
    );
  });
}
```

---

## 故障排查

### `Database is locked / LOCK file exists`

原因：前一次 Cognee 进程异常退出，留下 Ladybug 图数据库锁。

解决：适配层在每次 `ingest` 启动时自动清理残留锁。如果仍有问题：

```bash
# 手动清理
rm -f ~/my-blog/.cognee/databases/cognee_graph_ladybug/LOCK
```

### `No datasets found`

原因：尚未执行 `ingest`，或指定了错误的 dataset 名。

解决：先 `ingest`，确认 dataset 名一致。

### `fastembed is not installed`

原因：Cognee 的 embedding 引擎缺失（通常 uv sync 会安装）。

解决：

```bash
uv sync
# 或
pip install fastembed
```

### `HF_HUB_OFFLINE` 模式下首次运行

第一次运行需要下载 embedding 模型（~100MB）。确保网络畅通，不要设置 `HF_HUB_OFFLINE=1`。

### ingest 运行一半报错

查看错误信息：

- 如果是 `timeout` / `connection` / `503`：LLM 服务不可用，等恢复后重跑
- 如果是 `out of memory`：文件太大，考虑在 Obsidian 中拆分
- 其他错误会被收集，不影响其余文件继续处理

### 数据被"遗忘"了还能恢复吗

不能。`forget` 是物理删除 `.cognee/` 下的数据库文件，不可恢复。执行前会要求确认（除非 `--yes`）。
