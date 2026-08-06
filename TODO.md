# TODO: deep-obsidian

> 基于 [SPEC.md](docs/SPEC.md) 拆解。

## 依赖图

```
13 项目重命名 (deep-obsidian) ✅
 ├── 14 设置模块 (init/read/find_root) ✅
 │    ├── 15 重写 ingest (项目查找+错误提示) ✅
 │    │    ├── 16 重写 search (结构化检索) ✅
 │    │    │    ├── 17 新增 query (LLM 回答) ✅
 │    │    │    │    └── 18 重写 forget ✅
 │    │    │    └── 19 service (start/status/stop stub)
 │    │    └── 20 增量更新 (fingerprint) ✅
 │    └── 21 CLI 全面重构 (扁平化6命令) ✅
 └── 22 CI ✅
```

## Tickets

- [x] 13 项目重命名 → deep-obsidian, 66 tests
- [x] 14 设置模块 → 13 new tests
- [x] 15 ingest (项目查找+单文件) → 4 new tests
- [x] 16 search (结构化) → 3 new tests
- [x] 17 query (LLM 回答) → 3 new tests
- [x] 18 forget (项目查找) → integrated
- [x] 19 service (CLI stub) → start/status/stop 占位
- [x] 20 增量更新 (fingerprint) → 3 new tests
- [x] 21 CLI 重构 → 扁平 6 命令
- [x] 22 CI → GitHub Actions updated

## 测试总计

**242 tests, ~1s (unit) / mock LLM (integration+e2e)**

- 177 单元测试 (extractors + settings + service + ingest 辅助模块 + search helpers + logging_config 等，全部零 Cognee 依赖)
- 26 集成测试 (ingest/search/query/filters/incremental/service，全部使用 mock_llm)
- 39 e2e 测试 (CLI CliRunner，覆盖 init/ingest/search/query/forget/status + 中断处理)

> 数字已过期请直接跑 `uv run python -m pytest tests/ --collect-only -q` 更新，不要手动同步维护。
