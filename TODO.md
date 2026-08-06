# TODO: deep-obsidian

> 基于 [SPEC.md](docs/SPEC.md) 拆解。全部票据已完成。

## 已完成

- [x] 13 项目重命名 → deep-obsidian
- [x] 14 设置模块 (init/read/find_root)
- [x] 15 ingest (项目查找+错误提示)
- [x] 16 search (结构化检索)
- [x] 17 query (LLM 回答)
- [x] 18 forget
- [x] 19 service (start/status/stop + 文件监控常驻同步)
- [x] 20 增量更新 (fingerprint)
- [x] 21 CLI 全面重构 (扁平化 6 命令)
- [x] 22 CI → GitHub Actions
- [x] 23 跨进程并发安全与 ingest 运行态可观测性 (ADR-0008/ADR-0009)

## 测试总计

**277 tests**（实际数以 `uv run python -m pytest tests/ --collect-only -q` 为准。）

> 数字已过期请直接跑命令更新，不要手动同步维护。
