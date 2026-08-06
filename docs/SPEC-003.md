# SPEC-003: Ingest 进度可观测性 + 单例锁（`deep-obsidian status`）

> 状态：**待实现** · 关联 ADR：0009（跨进程 ingest 进度可观测性 + 单例锁）

---

## Problem Statement

作为 deep-obsidian 的使用者，我跑了一次长时间的全量 ingest（`--full --json`，非 TTY，比如后台/脚本方式），过程中完全无法从外部判断这个任务的状态：

- 进程是不是还活着？
- 卡在扫描、逐文件添加，还是语义推理（cognify）阶段？
- 处理到第几个文件了？

已有的 `ProgressCard` 实时进度条只在同进程、终端是 TTY 时才渲染——`--json` 模式、后台运行、被脚本调用时完全没有输出，日志文件在整个运行期间保持 0 字节。我只能靠猜（进程是否存活、`.cognee/` 目录体积变化）。

同时，目前没有任何机制阻止两个 ingest 同时对同一个 project 跑（比如 `service` 后台正在同步，我又手动在另一个终端跑了一次 `ingest --full`）——两者会同时写同一份 `hashes.json`/触碰同一个 Cognee 数据库，产生难以预料的竞态。

## Solution

新增一个顶层 `deep-obsidian status` 命令（注意：不是 `service status`，那个查的是文件监控常驻进程是否在跑，是另一个概念），一次性快照当前项目是否有 ingest 在跑、跑到哪个阶段。

配合这个命令，`ingest()` 核心运行期间会持久化一份跨进程可读的运行状态（不管调用方是 CLI 手动 ingest 还是 `service` 后台触发），这份状态同时兼作单例锁——同一个 project 同时只允许一个 ingest 在跑，撞锁时给出清晰反馈而不是产生数据竞态。

## User Stories

### status 命令

1. As a 用户，I want 运行 `deep-obsidian status` 看到当前项目是否有 ingest 在跑，so that 我不需要靠猜进程是否存活。
2. As a 用户，I want 在没有 ingest 运行时看到明确的"空闲"提示，so that 我知道可以放心地开始新的 ingest。
3. As a 用户，I want 在有 ingest 运行时看到它处于哪个阶段（扫描/逐文件添加/语义推理）、已运行多久，so that 我能判断它是不是卡死了还是正常在跑。
4. As a 用户，I want 在逐文件添加阶段看到具体的"第 N/共 M 个文件"和当前文件名，so that 我能估算还要等多久。
5. As a 用户，I want 在语义推理（cognify）阶段只看到"已运行 X 时长"而不是假装精确的百分比，so that 我不会被一个不存在的精确进度误导——cognify 本身是 Cognee 内部黑盒批量调用，没有细粒度进度可言。
6. As a 用户，I want 如果上一次 ingest 异常终止（进程被杀、崩溃），`status` 能告诉我"上次在处理第 N/共 M 个文件时异常退出"而不是显示误导性的"运行中"，so that 我知道数据可能处于不完整状态，需要重新 ingest。
7. As a 用户，I want `status` 支持 `--json`，so that 脚本/Obsidian 插件可以解析这个状态。
8. As a 用户，I want `status` 是一次性快照（不是持续刷新的 `--watch` 模式），so that 命令行为跟其他一次性命令（`ingest`/`forget`）一致，不引入新的交互范式。

### 单例锁

1. As a 用户，I want 当我手动跑 `ingest` 时project 已经有另一个 ingest 在跑（不管是另一个手动 ingest 还是 `service` 后台触发的），我要立刻看到清晰的错误（谁在跑、什么阶段、跑了多久），而不是两个进程互相踩数据或裸抛 Cognee 内部异常。
2. As a `service` 后台进程，I want 我自己触发的 ingest 撞上另一个正在跑的 ingest（比如用户手动跑了一次）时，安静跳过这一轮并记录一条警告日志，so that 一次瞬时锁冲突不会打断整个常驻监听服务；下一次文件事件或 30 秒轮询兜底会自然重试。
3. As a 开发者，I want 这个锁只在真的有实际工作（新增/修改/删除文件非零）时才生效，so that "全部文件都没变化"的快速路径（已有的性能设计）不会被无意义地加锁/解锁。

## Implementation Decisions

### 决定不做的事：cognify 阶段细粒度进度

调研确认 `cognee.cognify()` 是一次黑盒批量调用，没有暴露任何单条目/单文件级的进度回调；曾评估过"仿照 service 现有的逐文件触发模式，把批量 cognify 拆成多次小批调用"来换取更细粒度，但决定不做——会部分抵消项目里"积攒批量以控制 LLM 调用开销"这一既有设计取舍，且 cognee 内部跨文档实体合并/去重逻辑在拆批前后是否等价，当前没有任何回归测试覆盖，属于会改变图谱质量本身的架构级改动，不适合搭车在一个可观测性特性里顺带做。详见 ADR-0009。

结论：本特性的 `status` 在 cognify 阶段只报告"阶段 + 已运行时长"，不报告条目级百分比。

### 新模块：ingest 运行状态 + 锁

新增一个模块，专门owning"跨进程 ingest 运行状态文件"的格式、原子写入、独占锁语义和读取——这是因为有两个真实的、形态不同的调用方（写者 `ingest()`，读者 `status()`），共享同一份文件契约不应该分散实现两次。

接口形状（决策精度高于用散文描述，故内联；不代表最终文件路径/命名）：

```python
class IngestAlreadyRunningError(RuntimeError):
    """已有另一个存活的 ingest 持有锁。"""

def acquire(project_root, dataset, total) -> ProgressHandle:
    """独占创建运行状态文件；已有存活的运行状态则抛 IngestAlreadyRunningError；
    发现的是死亡进程留下的孤儿状态则清理后重试一次（复刻 service 的
    pidfile 独占创建+死锁重试模式）。返回一个 context manager——
    进入即已持锁，退出（无论正常返回还是异常）保证释放/清理，
    调用方不需要自己包 try/finally。"""

class ProgressHandle:
    def update(self, phase, current, total, current_file=""): ...

def read_state(project_root) -> dict | None:
    """纯读取，供 status() 使用；不参与锁语义，不会被误判为"抢锁"。"""
```

运行状态记录的字段：进程 pid、dataset 名、当前阶段（扫描/添加/cognify）、当前项/总项数、当前处理的文件名、启动时间。

复用已有的 `service` 模块中判断"pid 是否存活"的现成纯函数，不重构 `service` 模块本身（那部分代码已经工作、跟本特性无直接耦合）。

### `ingest()` 核心的改动

`ingest()` 在确定有实际工作（新增/修改/删除非零，即已有的"跳过 Cognee 初始化"快速路径判定之后）时获取上述运行状态锁；扫描阶段、逐文件添加阶段（每次进度回调）、cognify 阶段起始都更新一次状态；函数返回或抛出任何异常都会释放/清理该状态（结构性保证，不依赖调用方记得清理）。

这个改动是内建在 `ingest()` 核心里的，不是一个可选的回调/hook——这样 CLI 直接调用和 `service` 后台触发调用 `ingest()` 都天然获得这个能力，不需要每个调用方各自接线。这一点对 `service` 场景尤其重要：后台常驻运行、无人盯着终端，恰恰是最需要被 `status` 看到的场景。

### 撞锁时的行为分叉

- **CLI 手动 ingest 撞锁**：捕获 `IngestAlreadyRunningError`，向用户展示清晰的错误信息（谁在跑、什么阶段、启动了多久），退出码非零，而不是让 Cognee/文件系统层的原始异常冒泡。
- **service 后台触发的 ingest 撞锁**：捕获同一个异常，记一条 warning 日志，跳过这一轮，不让异常向上传播到 `run_service()` 的主循环——一次瞬时锁冲突不应该拖垮整个常驻进程。

### `status()` 的三态模型

对齐 `service_status()` 已有的三态风格（`running`/`stopped`/`stale_pid`），这里是：

- 运行状态文件不存在 → `idle`
- 文件存在 + pid 存活 → `running`（附阶段/进度/当前文件/启动时间）
- 文件存在 + pid 已死 → `stale`（附最后已知的进度快照 + 提示"进程异常退出，进度未清理"）

### CLI

新增顶层 `@main.command() def status()`（跟已有的 `service` 命令组平级，不挂在 `service` 子命令组下，避免跟"文件监控常驻进程是否在跑"的 `service status` 混淆）。支持 `--json`，输出跟其他命令（`ingest`/`forget`）风格一致。不支持 `--watch`——一次性快照即满足"能不能看到"这个原始需求，持续刷新跟 `ProgressCard` 已有的实时 UI 能力重叠，属于未被要求的范围。

## Testing Decisions

### 测试原则

沿用项目已有约定：只测公共行为、不测实现细节；单元测试零 Cognee 依赖、毫秒级；涉及真实 ingest 流程的用 mock LLM 的集成测试。

### 需要覆盖的关键场景

- 运行状态文件的写入/读取/原子性（临时文件 + `os.replace`，参考 `_fingerprint.py::save_hashes` 的既有测试方式）。
- 独占锁语义：第二次 `acquire()` 在锁被存活进程持有时抛 `IngestAlreadyRunningError`；在锁被死亡进程遗留（pid 已不存活）时能清理并重新获取成功。
- **模拟中途中断**（项目 AGENTS.md 明确要求的回归覆盖类别）：在 `on_progress` 回调执行到第 N 项时抛异常/模拟进程被杀，验证 (1) 运行状态文件里留存的是中断前最后一次成功更新的进度，(2) `status()` 能正确判定为 `stale` 并报告该进度，而不是误判为 `running` 或 `idle`。
- `status()` 三态分类的单元测试：无文件→idle，文件+存活 pid→running，文件+死亡 pid→stale。
- `service` 撞锁场景：`_on_file_event` 遇到 `IngestAlreadyRunningError` 时不崩溃、不向上传播，日志里能看到警告。
- CLI 集成测试（`CliRunner`）：`status --json` 输出结构；手动 ingest 撞锁时的错误信息和退出码。

## Out of Scope

- cognify 阶段的细粒度（条目级/百分比）进度——见上文"决定不做的事"，留给未来单独的 ADR 评估（需要先补图一致性回归测试）。
- `status --watch` 持续刷新模式。
- 跨进程读写并发（ADR-0008 记录的 `service` 写入与 `search`/`query` 读取之间的 Ladybug 锁冲突）——那是读写竞态，本特性解决的是写写竞态（两个 ingest 互斥），两者独立，互不依赖，不在本特性里一并解决。
- 重构 `service/_pidfile.py`/`start_service()` 去复用新模块的锁原语——那部分代码已经工作且跟本特性无直接耦合，不做无关重构；只从中 `import` 现成的"pid 是否存活"纯函数。

## Further Notes

- 运行状态文件是运行时产物（跟 `.deep-obsidian/hashes.json`、`.deep-obsidian/service.pid` 同级），不应提交到仓库，需要确认已被 `.gitignore` 覆盖（`.deep-obsidian/` 整体规则应该已经覆盖，需要核实新文件名不会意外漏出）。
- `service` 模块当前是`asyncio.Lock` 只在同进程内串行化文件事件触发的 ingest 调用——本特性新增的跨进程锁与它是互补关系（进程内 + 跨进程两层），不是替代关系。
