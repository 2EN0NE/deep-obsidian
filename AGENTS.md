# AGENTS.md — Cognee Obsidian 适配层

> AI Agent 参与本项目时的硬约束、设计理念与实现模式。
> 用户操作文档见 [README.md](README.md)，领域术语见 [CONTEXT.md](CONTEXT.md)。

---

## 核心红线（不可违反）

### ① 不直接操作 Cognee 内部图 API

Cognee 的 Ladybug 图引擎、内部 `create_node`/`create_edge` 等接口不在公共 API 合约内。**所有结构层图数据通过 `DataItem(data=text, external_metadata={...})` 传递**。

```python
# ✅ 正确
item = DataItem(data=text, external_metadata={"wikilinks": [...], "tags": [...]})
await cognee.remember(item, dataset_name=dataset)

# ❌ 禁止
cognee.graph.create_node(...)
cognee.graph.create_edge(...)
```

### ② Cognee 版本锁

```toml
# pyproject.toml
cognee>=1.4,<2.0
```

引入新 Cognee 接口必须在 CI 中验证低版本兼容。

### ③ 双层图不混淆

| 层 | 负责者 | 技术 |
|----|--------|------|
| **结构层** | `src/deep_obsidian/extractors/` | 纯 Python 正则 + YAML 解析 |
| **语义层** | Cognee cognify | LLM 推理 → 图节点/边 |

提取 wikilinks/frontmatter 时 **绝不调 LLM**。语义层上 **不假设结构层已建边**。

### ④ 数据跟 Vault 走

```python
cognee.config.data_root_directory = str(vault / ".cognee")
```

Cognee 所有持久化数据都在 vault 目录下。删除 vault 即删除所有数据。

---

## 设计理念

### 模块架构

```
src/deep_obsidian/
├── __init__.py              # 公共 API: ingest, search, status, forget
├── cli.py                   # Click CLI → 薄封装公共 API
├── ingest/
│   ├── __init__.py          # 入库管线编排
│   ├── _scanner.py          # os.walk vault → list[Path]
│   ├── _progress.py         # ProgressStore: JSON 持久化的完成集合
│   ├── _health.py           # Ladybug 锁检测与清理
│   └── _fingerprint.py      # SHA-256 文件指纹
├── search/
│   └── __init__.py          # 包装 cognee.recall → 结构化 dict + layer
├── extractors/
│   ├── __init__.py
│   ├── wikilinks.py         # 纯函数: [[target|alias]] → list[dict]
│   ├── frontmatter.py       # 纯函数: YAML --- block → dict
│   └── tags.py              # 纯函数: #tag + frontmatter tags → list[str]
├── forget.py                # 包装 cognee.forget
├── query.py                 # LLM 问答（检索 + 合成）
├── settings.py              # .deep-obsidian/settings.json 读写
└── status.py                # 进度状态查询
```

**关键约束：**

- `extractors/` 三个模块是纯函数，**零 Cognee 依赖**
- Cognee 集成点通过公共 API 暴露：`ingest`（`cognee.remember`）、`search`（`cognee.recall`）、`forget`（`cognee.forget`）。各模块直接调用 Cognee 以保持薄封装——未来如替换后端，只需改这三个模块
- 每个公共 API 函数独立成模块（`forget.py`、`status.py`），禁止循环 import
- **惰性导入**：`__init__.py` 使用 PEP 562 `__getattr__` 延迟加载子模块，避免 `import deep_obsidian` 触发 Cognee 初始化。`--help` 和 `--version` 因此没有日志噪音
- **日志**：CLI 入口通过 `LOG_LEVEL=ERROR` 环境变量抑制 Cognee 的控制台输出。用户用 `DEEP_OBSIDIAN_DEBUG=1` 或 `--debug` 开启详细日志。不要操作 `sys.stderr` 做日志抑制

### 为什么会变慢？测试怎么加速？

Cognee 是重量级依赖。import cognee 需要 2-3 秒。解决：

- **单元测试**（`tests/unit/`）不 import Cognee，毫秒级
- **集成测试**（`tests/integration/`）用 `mock_llm` fixture（patch `cognee.api.v1.cognify.cognify`）替换 cognify 阶段，避免真实 LLM 调用
- 开发时只跑单元测试：`uv run pytest tests/unit/`

---

## 实现模式

### 测试模式

**单元测试（纯函数，毫秒级）：**

```
tests/unit/
├── test_wikilinks.py      12 tests — [[简单]]、[[带|别名]]、[[路径/笔记]]、代码块忽略
├── test_frontmatter.py    10 tests — 标准 YAML、空、损坏、嵌套、中文
├── test_tags.py           11 tests — frontmatter tags、#inline、中文、合并去重
├── test_scanner.py         9 tests — 平坦目录、嵌套、.开头的跳过、不存在报错
├── test_progress.py        7 tests — 持久化、加载、标记、重置、损坏恢复
└── test_health.py          5 tests — 锁检测、PID kill、无锁返回
```

**集成测试（需要 Cognee + mock LLM）：**

```
tests/integration/
├── conftest.py             — mock_llm + vault fixtures
├── test_ingest.py          6 tests — 基本入库、元数据写入、增量跳过、长文本
├── test_search.py          3 tests — 召回、层级标注、空数据集
└── test_filters.py         3 tests — tag过滤、wikilink过滤、空结果
```

**测试原则：**

- 只测公共 API 行为，不测私有函数
- mock 只用于隔离 LLM（`cognify`），其余用真实 Cognee
- `mock_llm` fixture 使用 `unittest.mock.patch` 替换 `cognee.api.v1.cognify.cognify`

### CLI 模式

CLI 是 Python API 的薄封装。命令对应关系：

| CLI | Python API |
|-----|-----------|
| `ingest <path>` | `ingest(path)` |
| `search <query>` | `search(query)` |
| `query <question>` | `query(question)` |
| `status` | `status()` |
| `forget` | `forget()` |

CLI 输出默认人类友好，`--json` 给 TS 消费。

### 错误处理模式

```python
# ingest 循环：单文件失败不中断整批
try:
    await _ingest_one(filepath, dataset)
    success += 1
except _LLMDegradedWarning as e:
    # LLM 挂了但结构数据已写入 → 算成功，记警告
    all_warnings.append(str(e))
    success += 1
except Exception as e:
    # 其他错误 → 算失败，继续下一个
    failed += 1
```

### 文件指纹模式

增量更新用 SHA-256 前 16 位哈希比对：

```python
def file_hash(filepath: str) -> str:
    return hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:16]
```

---

## 已发现的陷阱

### Mock cognee.cognify 的正确方式

`cognee.remember()` 内部延迟 import `cognify`：

```python
# remember.py 内部（函数体内）
from cognee.api.v1.cognify import cognify
```

所以 mock 必须 patch **源模块的属性**，不是目标模块：

```python
# ✅ 正确
with patch("cognee.api.v1.cognify.cognify", new=_fake):
    await cognee.remember(item)

# ❌ 无效
with patch("cognee.api.v1.remember.remember.cognify", new=_fake):
    ...  # lazy import 会重新绑定真实 cognify
```

### data_root_directory 必须在 scan 之后设置

`cognee.config.data_root_directory = ...` 可能触发文件系统副作用（创建 `.cognee/` 目录）。必须在 `scan_vault()` 之后执行，否则扫描结果的 `os.walk` 排序可能受影响。

### fastembed 是运行时依赖

Cognee 的嵌入引擎依赖 `fastembed`。如果 `uv sync` 跳过了，ingest 时会炸 `ModuleNotFoundError: No module named 'fastembed'`。已在 `pyproject.toml` 中显式依赖。

### Cognee 鉴权默认开启

Cognee 1.x 默认开启多用户鉴权。单机使用必须：

```bash
export ENABLE_BACKEND_ACCESS_CONTROL=false
export COGNEE_SKIP_CONNECTION_TEST=true
```

### uv sync --dev vs uv sync

开发依赖（pytest 等）在 `[dependency-groups] dev` 下，必须 `uv sync --dev` 才能安装。
