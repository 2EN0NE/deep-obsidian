# 修复两个跨 vault 数据串门的 bug：缺失 system_root_directory + forget --all 误用 everything=True

在为测试保障体系补充回归测试时，用真实（非 mock）的 `cognee.add()`/`cognee.recall()`/`cognee.forget()`
做往返验证时发现：`ingest()`/`forget()` 只设置了 `cognee.config.data_root_directory`，`search()`
则完全没有设置任何隔离配置；而 `forget --all` 对 Cognee 底层 API 的调用方式会删除**当前机器上这个
Cognee 安装的全部数据集**，不是"这一个 vault 的 dataset"。

## Bug 1：`system_root_directory` 从未设置，vault 隔离是假的

AGENTS.md「核心红线④」写的是：

```python
cognee.config.data_root_directory = str(vault / ".cognee")
```

并声称"Cognee 所有持久化数据都在 vault 目录下。删除 vault 即删除所有数据"。

但实测（cognee==1.4.1）显示：`data_root_directory` 只重新定位了原始文件的存储位置；
真正被 `add()`/`cognify()`/`recall()`/`forget()` 读写的图数据库、向量数据库、关系数据库
（Cognee 称为"system" 存储）由**另一个独立配置项** `cognee.config.system_root_directory`
决定，默认值是相对于当前工作目录/安装包位置的固定路径（本项目环境下落在
`.venv/lib/pythonX.Y/site-packages/cognee/.cognee_system/`），与 `data_root_directory`
完全无关，且从未被这三个模块设置过。

实测复现：在一个全新的临时目录里设置 `data_root_directory` 后调用 `add()` + `recall()`，
`recall()` 返回的却是**这台机器上此前用这个 Python 环境处理过的、完全不相关的另一个
数据集**的内容——图数据库其实一直指向 Cognee 的默认位置，从未真正跟着 vault 走。

`search()` 更严重：它完全没有设置 `data_root_directory`/`system_root_directory`，
意味着一次裸调用 `search()`（例如未来某个长驻进程、或 REPL 里先调 `search()` 后调
`ingest()`）会直接命中 Cognee 的默认 system 存储，而不是当前项目的 `.cognee/` 目录。

### 修复

`ingest()`、`forget()`、`search()` 三个 Cognee 集成点统一在初始化时设置：

```python
cognee.config.data_root_directory = str(project_root / ".cognee")
cognee.config.system_root_directory = str(project_root / ".cognee")
```

两者都指向同一个 vault 本地目录，让「核心红线④」的承诺（删除 vault = 删除所有数据）
第一次真正成立。

## Bug 2：`forget --all` 用 `everything=True` 删掉了所有 vault 的数据

`forget.py::_forget_all()` 原实现：

```python
await cognee.forget(dataset=dataset_name, everything=True)
```

cognee 的 `forget()` API 文档（`cognee/api/v1/forget/forget.py`）写得很明确：

> `everything`: If True, delete all datasets and data the user owns.
> **Ignores `data_id`, `dataset`, and `dataset_id`.**

也就是说同时传 `dataset=` 和 `everything=True` 时，`dataset` 会被**直接忽略**，
`everything=True` 单独触发 `_forget_everything(user)`——删除这个 Cognee "user"
拥有的**全部数据集**，不是这一个 dataset。实测复现：调用一次
`cognee.forget(dataset="probe_ds", everything=True)`，日志输出
`forget: deleted all data for user=... (15 datasets)`——machine 上这个 Cognee
安装此前积累的 15 个数据集全部被清空，而不是仅有的那一个。

由于本项目默认关闭多用户鉴权（`ENABLE_BACKEND_ACCESS_CONTROL=false`），同一台机器
上所有 deep-obsidian 项目共享同一个默认 Cognee user——这意味着**在任意一个 vault 里
运行一次 `deep-obsidian forget --all`，会连带清空这台机器上其他所有 vault 的知识图谱**，
且这些 vault 需要重新 `ingest`（重新消耗一遍 LLM 调用）才能恢复。CONTEXT.md 对
`forget --all` 的文档描述是"清空整个 dataset"，从未提示过这个副作用。

### 为什么会漏测

`tests/conftest.py` 的 `mock_llm` fixture 直接 mock 掉了 `cognee.forget`，mock 函数
接受任意合法关键字组合、永远返回 `None`，不区分"只删一个 dataset"和"删这个 user 的
全部 dataset"这两种语义完全不同的调用。已有的
`tests/e2e/test_e2e.py::TestForgetE2E::test_forget_all_clears_everything` 只断言了
本地 `hashes.json` 被清空，同样不会区分这两种语义——本地状态在两种情况下看起来
完全一样，唯一的差别在被 mock 掉的那一层。

### 修复

```python
await cognee.forget(dataset=dataset_name)
```

去掉 `everything=True`。cognee 文档里"删除一整个 dataset"的标准用法就是单独传
`dataset=`。

### 配套的测试标准

> 任何调用第三方 API 时传了多个"作用域"相关的关键字参数（本例中 `dataset` +
> `everything`），必须去读该 API 的文档确认参数间的优先级/互斥关系，不能假设"参数
> 都传了就是它们的并集"。回归测试里必须直接断言传给第三方 API 的实际关键字参数
> （而不仅仅断言本地可观察的副作用），因为 mock 会让两种完全不同语义的调用在测试里
> 长得一样。参见 `tests/unit/test_forget_helpers.py::TestForgetAllScope`。

## 权衡

- **代价**：这两个修复都是几行改动，没有性能/复杂度代价。
- **收益**：`forget --all` 不再有跨 vault 误删风险；`data_root_directory` 单独设置
  产生的"看起来隔离了但其实没有"的假隔离感被消除。
- **遗留风险**：即使 `system_root_directory` 正确隔离了物理存储位置，`cognee.recall()`
  的 `datasets=[...]` 过滤器在部分查询模式下（实测：`query_router` 落到
  `GRAPH_COMPLETION` 默认分支时）是否严格按 dataset 过滤未被完全验证——这是
  P0 用例缺口（真实 Cognee 往返契约测试缺失）留下的后续调查项，本次修复没有解决，
  只是把物理存储位置修正为了正确的隔离前提。
