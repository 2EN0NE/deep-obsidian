# ADR 0007: `cognee.config.X` 必须以函数调用设置，属性赋值是静默的空操作

**状态**: 已修复
**日期**: 2026-08-06
**决策者**: 工程讨论（延续 ADR-0006）

---

## 背景

ADR-0006 已经发现并"修复"了一个 bug：`ingest()`/`forget()`/`search()` 只设置
`data_root_directory`，从未设置 `system_root_directory`，导致图/向量/关系数据库
从未真正跟着 vault 走。ADR-0006 给出的修复代码是：

```python
cognee.config.data_root_directory = str(project_root / ".cognee")
cognee.config.system_root_directory = str(project_root / ".cognee")
```

这次在排查一个看起来不相关的问题（`obsidian-test` 测试数据集条目数远超实际文件数、
`forget --all` 后重新 ingest 报 Ladybug 图数据库锁文件损坏）时，发现 `obsidian-test/`
目录下从未生成过 `.cognee/` 子目录——ADR-0006 的修复代码从**运行时就没有生效**。

## 根因

`cognee.config` 是一个类（不是实例），`cognee.config.data_root_directory` 是这个类
上的一个 `@staticmethod`。Python 允许对类属性做**属性赋值**：

```python
cognee.config.data_root_directory = str(project_root / ".cognee")
```

这行代码语法上合法、pyright 不会报错、运行时也不抛异常——但它做的事情只是把
`data_root_directory` 这个类属性**替换成一个字符串**，同一进程里后续任何代码
`cognee.config.data_root_directory(...)`（把它当函数调用）会立刻因为"str 不可调用"
而 `TypeError`；但如果后续代码从未真正调用它（就像本项目 ingest/forget/search
三个模块里那样，赋值完就再没碰过这个名字），这个错误永远不会被触发，看起来
"什么都没发生"。

Cognee 真正读取配置的路径是：

```python
# cognee 内部
base_config = get_base_config()  # @lru_cache 记忆化
base_config.data_root_directory = data_root_directory  # 这是 staticmethod 函数体内的赋值
```

也就是说 `data_root_directory` 本该被**调用**（作为函数），由函数体内部去更新
`get_base_config()` 返回的、真正被 `add()`/`cognify()`/`recall()`/`forget()` 读取的
那个记忆化配置对象。属性赋值完全绕过了这条路径。

正确写法：

```python
cognee.config.data_root_directory(str(project_root / ".cognee"))
cognee.config.system_root_directory(str(project_root / ".cognee"))
```

### 实测验证

```python
>>> import cognee
>>> cognee.config.data_root_directory = "/tmp/should-not-work"  # 属性赋值
>>> from cognee.base_config import get_base_config
>>> get_base_config().data_root_directory  # 完全没变，还是 Cognee 的默认路径
'.../cognee/.data_storage'
>>> cognee.config.data_root_directory("/tmp/should-work")  # 函数调用
>>> get_base_config().data_root_directory
'/tmp/should-work'  # 生效了
```

## 影响范围

自本项目开始以来（包括 ADR-0006 声称已修复之后），**所有 vault 的全部 Cognee 数据
一直写入同一个机器/venv 级别的共享全局存储**
（`.venv/lib/python3.X/site-packages/cognee/.cognee_system/` 和 `.data_storage/`），
从未真正按 vault 隔离。AGENTS.md「核心红线④」"删除 vault 即删除所有数据"的承诺，
从项目立项到这次发现为止，**从未真正成立过**。

这也解释了两个此前看起来无关的现象：

- `obsidian-test` 数据集的条目数（226）远超其实际文件数（约 75）——因为这个共享
  全局存储里累积了历史上所有临时测试脚本、其他 vault 的 ingest 结果。
- `forget --all` 后重新 ingest 时 Ladybug 图数据库报 `.lbug.shadow` 文件缺失/损坏——
  长期被大量互不相关的进程/脚本并发写入同一个共享存储，图引擎的 shadow 文件被破坏。

## 修复

将 `search/__init__.py`、`ingest/__init__.py`（2 处调用点）、`forget.py` 中全部
8 处 `cognee.config.data_root_directory = ...` / `cognee.config.system_root_directory = ...`
改为函数调用形式。

同时清理了 `.venv` 内损坏的全局共享存储（可重建的缓存，非真实用户数据），并对
`obsidian-test` 做了一次干净的全量重新 ingest 以验证隔离修复后数据真正落在
`obsidian-test/.cognee/` 下。

## 遗留风险 / 后续行动

- **历史数据未迁移**：任何在这次修复之前 ingest 过的真实 vault，其数据仍然躺在
  旧的共享全局存储里，而不是各自的 `vault/.cognee/` 下。这些 vault 需要重新
  `ingest --full` 才能获得真正隔离、且 `search()` 能正确解析 `source_file` 的数据
  （见下方关联发现）。本 ADR 不负责逐一迁移，只记录这个缺口。
- **测试盲区**：ADR-0006 的回归测试断言的是"设置了 `system_root_directory`"这个
  调用**发生过**，而不是"这个调用真的改变了 Cognee 的实际配置状态"。类似
  ADR-0006 结尾提到的测试标准——mock 或浅层断言会让"看起来对但语法错误的调用"
  和"真正生效的调用"在测试里长得一样。理想情况下回归测试应该在设置后读取
  `get_base_config()`（或等价的可观察状态）来确认真的生效，而不仅仅断言
  `cognee.config.X` 被"设置"过。

## 关联发现：`document_name` 几乎总是内容哈希，不是真实文件名

在验证隔离修复期间，顺带发现 `search()` 此前依赖的 `document_name`（用于反查
`source_file`）在当前 ingest 实现下几乎总是 Cognee 内部生成的 `text_<hash>`，
不是真实文件名——因为 `_build_data_item()` 把笔记内容作为**原始字符串**传给
`DataItem(data=text, ...)`，Cognee 从未见过真实文件路径，其 `TextChunker` 在这种
情况下用一个临时文件的 basename 作为 `document.name`。

真正可靠的关联字段是 chunk 元数据里的 `document_id`（Cognee 文档明确说明这等于
被摄入的 Data 记录自身的 id），它跟本项目 `hashes.json` 里记录的 `data_id`
精确匹配。`search()` 已改为优先按 `data_id` 精确反查 `hashes.json`，`document_name`
的 stem 匹配降级为兜底方案（仅用于没有可用 `hashes.json` 的场景，如不带
`vault_path` 的编程式调用）。
