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
cognee.config.data_root_directory(str(vault / ".cognee"))
cognee.config.system_root_directory(str(vault / ".cognee"))
```

Cognee 所有持久化数据都在 vault 目录下。删除 vault 即删除所有数据。

**注意：`cognee.config.X` 是类上的 staticmethod，必须以函数调用的形式设置** ——
`cognee.config.data_root_directory = str(...)` 这种属性赋值语法看起来会通过
pyright/运行时检查（因为 Python 允许覆盖类属性），但它只是把这个类属性替换成了一个
字符串，从未调用过 Cognee 内部真正读写 `get_base_config()`（`@lru_cache` 记忆化）的
setter 逻辑，对 Cognee 的实际配置**零效果**。这个错误曾经真实存在于本项目的
ingest/forget/search 三个模块里、且被 ADR-0006 当作"已修复"记录下来，实际上从未
生效过。详见 [ADR-0007](docs/adr/0007-config-setter-must-be-called-as-function.md)。

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
| `forget <targets...>` | `forget(targets=[...])` |
| `forget --all` | `forget(all=True)` |

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

### install.sh 约定（ADR-0013）

- **职责边界**：`install.sh` 只管环境检测 + 依赖安装 + 验证（能执行 `deep-obsidian`）；交互式配置引导是 `deep-obsidian init` 的事，install.sh 不做配置。
- **幂等**：`.venv/` 已存在则走修复式刷新（每次 `uv sync`，uv 已最新时秒级），`--reset` 才删 `.venv/` 重建。
- **不静默安装**：缺 Python/uv/git 时给出明确命令让用户确认后执行（不推荐编译 Python 等高风险操作）。
- **可观测性**：
  - 全程日志写 `logs/install.log`（带时间戳），终端只显示精简进度。
  - `--check` 只跑环境检测、输出 JSON——是测试（bats/e2e）与用户排障的稳定接口，改动它必须同步改 `tests/bats/` 与 `tests/e2e/test_install_sh.py`。
  - 脚本开头注释块写明职责、可观测性、用法；结尾打印下一步指引。
- **bash 兼容**：macOS 自带 bash 3.2，不要用 `${var,,}` 等 bash 4+ 特性（用 `tr` 做大小写转换）。
- **平台**：macOS first，`PLATFORM` 检测预留 Linux/Windows 扩展点。

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

### 逐项处理 + 落盘 checkpoint 的循环，必须逐项持久化

`ingest()` Phase 1 曾经只在整个 for 循环跑完之后调用一次 `save_hashes()`。中途被打断（Ctrl+C / kill / 崩溃）会让所有已经成功 `cognee.add()` 的文件的进度全部丢失，下次运行把它们当新文件重新处理，在 Cognee 图谱里产生重复节点。详见 [ADR-0005](docs/adr/0005-incremental-checkpoint-persistence.md)。

**规则（适用于本项目所有类似循环，写代码和审代码时都要检查）：**

- [ ] 任何"逐项处理外部资源（网络调用 / LLM 调用）+ 落盘 checkpoint"的循环，必须在**每一项处理成功后立即持久化**，不能只在整批循环结束后统一存一次。
- [ ] 高频写入的状态文件（如 `hashes.json`）必须原子写入（临时文件 + `os.replace`），不能直接 `write_text()` 覆盖，避免进程被杀导致文件截断/损坏。
- [ ] 任何声称支持"可中断、重新运行可恢复/不重复处理"的功能，回归测试必须包含至少一个**模拟循环中途中断**的用例（用 `on_progress` 回调在第 N 项时抛异常），验证：(1) 中断前已完成的部分被正确持久化，(2) 恢复后不会被重复处理。仅测试"完整成功"和"完全失败"两种边界不足以覆盖这类 bug。参见 `tests/integration/test_interrupt_resilience.py`。
- [ ] CLI 命令的异常处理不能只写 `except Exception`——`KeyboardInterrupt` 不继承自 `Exception`，Ctrl+C 会绕过它直接抛出裸 traceback。必须显式 `except KeyboardInterrupt` 给出清晰退出信息（退出码 130）。

### checkpoint 不能盲目信任：必须验证 dataset 在 Cognee 中仍然存在

`hashes.json` 里的 data_id 引用 Cognee 数据库中的 entities。如果 Cognee 数据库被重建（venv 重建、`uv sync`、换机器 clone），这些 data_id 变成悬空引用。但 `ingest()` 曾经只看文件 hash —— hash 匹配就跳过，从不验证 dataset 是否存在于 Cognee。结果：`ingest` 报告"75 unchanged"（实际零条数据入库），`search` 报 `DatasetNotFoundError`。详见 [ADR-0005](docs/adr/0005-incremental-checkpoint-persistence.md)。

**规则**：

- [ ] 当所有文件都被 hash 跳过（`unchanged_count > 0, total == 0`）时，必须先验证 dataset 在 Cognee 中存在（`cognee.datasets.list_datasets()`）。不存在则强制全量重建。
- [ ] `mock_llm` fixture 必须同步 mock `cognee.datasets.list_datasets()`，否则所有依赖该 fixture 的测试在 stale-guard 路径上会调用真实 Cognee API。

### 每个 Cognee 集成点必须同时设置 data_root_directory 和 system_root_directory

只设置 `cognee.config.data_root_directory` 不能让数据真正跟着 vault 走——实际被 `add()`/`cognify()`/`recall()`/`forget()` 读写的图/向量/关系数据库位置由 `cognee.config.system_root_directory` 决定，未设置时默认落在一个固定的、machine/venv 级别的共享位置，所有 vault 会读写同一份数据库。`ingest()`、`forget()`、`search()` 三个模块都必须在触碰 Cognee 之前把两者一起设成 `str(project_root / ".cognee")`——并且必须以**函数调用**形式设置（`cognee.config.data_root_directory(...)`），不是属性赋值，见上面「④ 数据跟 Vault 走」和 [ADR-0007](docs/adr/0007-config-setter-must-be-called-as-function.md)。详见 [ADR-0006](docs/adr/0006-vault-isolation-and-forget-all-scope.md)。

### 调用第三方 API 时，多个「作用域」参数不能假设是并集

`cognee.forget(dataset=X, everything=True)` 曾被误用为"删除 dataset X 的全部数据"，但 `everything=True` 的真实语义是"忽略 dataset/dataset_id/data_id，删除这个 Cognee user 拥有的全部数据集"——`forget --all` 曾因此清空过同一台机器上其他 vault 的知识图谱。**规则：**调用任何第三方 API 时如果同时传了多个可能限定作用域的关键字参数，必须先读文档确认它们的优先级/互斥关系，不能假设它们是并集；对应的回归测试必须直接断言传给第三方 API 的实际关键字参数，而不能只断言本地可观察的副作用（mock 会让两种不同语义的调用在测试里长得一样）。参见 [ADR-0006](docs/adr/0006-vault-isolation-and-forget-all-scope.md) 和 `tests/unit/test_forget_helpers.py::TestForgetAllScope`。
