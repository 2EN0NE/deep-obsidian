# ADR 0008: Service 常驻同步与 search/query 并发时的图数据库锁冲突

**状态**: 已决定 → 方案 1（CLI 层重试 + 友好提示）
**日期**: 2026-08-07
**决策者**: 工程讨论

---

## 背景

Cognee 底层的图数据库（Ladybug，kuzu 实现）**不支持并发的读写混用**——同一份
`.cognee/` 数据库文件同时只能被一个持有写锁的进程独占访问，其他试图读取
（`search`/`query`）或写入（`ingest`）的进程会直接报错，而不是排队等待。

`service start` 启动后台常驻进程，会持续监听 vault 文件变更并自动触发
`add()` + `cognify()`（写入图数据库）；用户在同一个 vault 上手动跑
`search`/`query`（读取图数据库）如果恰好撞上 service 正在写入的那个时间窗口，
就会失败。

## 复现

手动模拟：对同一个 vault，一个终端跑 `deep-obsidian ingest --full`（长时间
持续 cognify，模拟 service 后台同步中），另一个终端并发跑 `search`：

```text
Error: IO exception: Could not set lock on file
.../c738e6f5-....lbug (Lock is held by PID <ingest 进程 PID>)
```

实测中，这个错误**不是每次都触发**——Ladybug 似乎只在特定的写入时刻（如
提交一批新节点/边）持锁，其余时间窗口读操作可以正常穿插进行。这意味着这是一个
**间歇性、时间窗口敏感**的问题，偶尔手动测试很容易误判为"没问题"，但在
service 长期运行、且用户频繁交互式 search 的真实使用场景下，撞上这个窗口的
概率会累积。

## 影响范围

- `service` 是本项目为"持续同步"设计的常驻功能（ADR-0004）。它的核心场景就是
  长时间在后台运行、随时可能在写图。这跟"用户随时可能手动 search/query"这两个
  使用场景**结构性冲突**——只要 service 在跑，search/query 就有非零概率失败。
- 已有的 `clear_ladybug_lock()`（见 `docs/USER_GUIDE.md` "Database is locked"
  一节）只清理**进程已退出后残留的死锁文件**，对"另一个进程正持有的、合法的
  活跃锁"无效也不应该无效（清理活跃锁会破坏正在进行的写入）。
- 目前没有任何重试/排队机制：`search()`/`query()` 遇到这个锁错误会直接把
  Cognee 的原始 `IOException` 冒泡给用户，没有更友好的提示（比如"service 正在
  同步，请稍后重试"），也没有自动重试。

## 可能的应对方向（未决定，本 ADR 只记录问题）

1. **CLI 层重试 + 友好提示**：`search`/`query` 遇到 Ladybug 锁错误时，识别该
   错误类型，做有限次数的指数退避重试，重试仍失败则给出"vault 正在被 service
   同步，请稍后再试"而不是裸的 IOException 堆栈。成本最低，但不能消除失败，
   只是把体验做得更好。
2. **service 侧短暂让锁**：service 的每次 cognify 批处理之间插入一个"空档期"，
   在此期间不持有写锁，让并发读请求有更大概率穿插进去。治标不治本，仍然是
   概率性的。
3. **单进程仲裁（读写都走 service）**：如果 service 在运行，CLI 的 search/query
   不直接读 Cognee，而是通过 IPC 转发给 service 进程，由 service 内部串行化
   所有读写操作。这是最彻底的方案，但工程量大，且需要设计 IPC 协议（本项目当前
   `service` 模块的 IPC 部分参见 `.scratch/incremental-sync-service/issues/07-ipc.md`，
   处于规划阶段，尚未实现）。
4. **不解决，只文档化**：明确告知用户"service 运行期间手动 search/query
   有小概率失败，重试即可"，作为已知限制写进 `docs/USER_GUIDE.md` 的
   troubleshooting，不做代码改动。

## 决定

采用 **方案 1（CLI 层重试 + 友好提示）**，原因：

- 成本最低：只需在 `search/__init__.py` 中新增一个 ~30 行的 `_recall_with_retry()`
  辅助函数，不涉及 service 侧改动、IPC 协议或 Cognee 内部修改。
- 效果足够：Ladybug 的写锁是短暂的（仅在 cognify 一批数据提交时持锁），
  指数退避重试（最多 3 次，1s / 2s / 4s）在绝大多数情况下都能等到锁释放。
- 可回退：如果未来发现重试成功率不理想，仍可追加方案 2 或 3，
  重试层本身不会被废弃（它作为"最后一道防线"仍有价值）。
- 非锁错误直接传播：config/auth 问题不会被重试延迟掩盖。

## 实现（2026-08-07）

- `src/deep_obsidian/search/__init__.py`：新增 `_recall_with_retry()`，替换
  `asyncio.gather` 内直接调用的 `cognee.recall()`。关键词匹配 "lock" / "io exception"
  识别 Ladybug 锁错误；非锁错误立即 `raise`。
- `tests/integration/test_search_lock_retry.py`：3 个测试——锁错误自动重试成功 /
  重试耗尽后友好报错 / 非锁错误不重试直接传播。

## 现状

**已实现。** `search()` 遇到 Ladybug 锁错误时自动重试最多 3 次，全部失败后给出
"知识图谱正在被写入，请稍后重试"的友好提示（不再是裸 IOException 堆栈）。
