# 跨进程 ingest 进度可观测性 + 单例锁

用户观察到一次后台全量 ingest（`--full --json`，无 TTY）跑了近 3 小时，期间完全无法从外部判断"进程是死是活、卡在哪个阶段"——`--json` 模式下没有中间输出，日志文件在整个运行期间是 0 字节，唯一线索是 `.cognee/` 目录大小的间歇性观察和进程存活检测。已有的 `ProgressCard`（`ingest/_progress.py`）只在同进程、`stderr.isatty()` 为真时渲染，天然不覆盖这个场景。

决定新增一个顶层 `deep-obsidian status` 命令，配合 `ingest()` 核心内建写入的 `.deep-obsidian/progress.json`，解决"能不能看到"的问题；同时把这个文件兼作跨进程互斥锁，解决"会不会两个 ingest 同时跑互相踩"的问题。

## 决定

- **只做可观测性，不做 cognify 阶段的细粒度进度。** `cognee.cognify()` 是一次黑盒批量调用，没有暴露任何单条目进度回调（`chunks_per_batch`/`data_per_batch` 只是内部批大小配置，不是进度钩子）。曾评估"仿照 service 路径，把批量 cognify 拆成多次小批调用"来换取更细的进度粒度，但拒绝了这个方向：
  - 会部分抵消 CONTEXT.md《批量 cognify》一节记录的既有设计初衷——积攒批量调用本来就是为了控制调用次数/开销。
  - cognee 内部的跨文档实体合并/去重逻辑在"一次大批 cognify() vs 多次小批 cognify()"两种调用方式下是否等价，本项目没有任何回归测试覆盖——这改的是图谱质量本身，不是一个可以轻率验证的 UI 特性。
  - 即使拆批，单次 `cognify()` 调用内部仍是黑盒，只是把"卡住看不到进度"的窗口从"一次全量"缩小成"一个批次"，边际收益有限。
  - 结论：`status` 在 cognify 阶段只报告 `phase=cognify` + 已运行时长，不报告条目级百分比。拆批提升粒度作为独立话题留给未来单独评估，需要先补图一致性的回归测试。

- **`progress.json` 内建在 `ingest()` 核心，不是可选 callback。** 让 CLI 直接 ingest 和 service 后台触发的 ingest 都能被 `status` 看到，不需要每个调用方各自接一份 wiring；否则 service 后台运行——恰恰是最需要外部可观测性的场景——反而拿不到这个能力。清理用 `try/finally` 保证正常结束/异常退出都删除文件，只有硬杀（SIGKILL）才会留下孤儿文件。

- **`progress.json` 兼作单例锁**（`O_CREAT|O_EXCL` 独占创建，复用 `service.pid` 已有的死锁检测+重试一次模式）。同一 project 同时只允许一个 ingest 在跑。只在确定有实际工作（新增/修改/删除非零）时才加锁——匹配 `ingest()` 已有的"全部 unchanged 时跳过 Cognee 初始化"快速路径，避免每次 service 30s 轮询空转都产生文件 I/O。
  - `service` 撞锁时静默跳过这一轮、记 warning 日志，**不**让异常向上冒泡——一次瞬时锁冲突不该拖垮整个常驻进程；下一次文件事件或 30s 轮询兜底会重试。
  - 手动 CLI ingest 撞锁时给出清晰错误（谁在跑、什么阶段、多久了），而不是裸抛 Cognee/文件系统异常。

- **三态模型**（对齐 `service_status()` 已有的 `running`/`stopped`/`stale_pid` 风格）：
  - 文件不存在 → `idle`
  - 文件存在 + `pid` 存活 → `running`（附 phase/current/total/current_file/started_at）
  - 文件存在 + `pid` 已死 → `stale`（附最后已知进度 + "进程异常退出，进度未清理"提示）

- **`status` 命令只做一次性快照 + `--json`，不做 `--watch` 持续刷新。** 原始需求是"能不能看到"，不是"要不要实时刷新"——`--watch` 会跟 `ProgressCard` 已有的实时 UI 功能重叠，属于未被要求的能力。

## 权衡

- 跨进程锁把这个特性的范围从"只读可观测性"扩大到"顺带解决一个真实存在的并发写入竞态"，工程量比纯只读方案大，但用户在追问中明确选择了这个方向（而不是"只记录限制，不修"），换来的是 `status` 输出不会因为两个进程同时写同一份文件而闪烁/显示错的进程状态。
- 没有解决的相邻问题：`search`/`query` 读操作与 `service` 写操作之间的 Ladybug 图数据库锁冲突（见 ADR-0008）——那是读写并发问题，这个 ADR 解决的是写写并发（两个 ingest 互斥），两者独立，不互相依赖。
