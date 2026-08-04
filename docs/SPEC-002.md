# SPEC-002: 日志体系、CLI 静默与错误处理规范化

> 状态：**已实现** · 关联 ADR：0001（Cognee 版本锁）、0002（双层图）

---

## Problem Statement

作为 deep-obsidian 的使用者，我遇到三个痛点：

1. **CLI 噪音**：运行 `deep-obsidian --help` 时看到大量 Cognee 的 structlog 输出（"Log file created at..."、"Cognee 1.0 changes..."），这些底层日志和我的 CLI 帮助混在一起，毫无价值。
2. **日志散落**：deep-obsidian 作为中间层没有自己的日志。Cognee 的日志在 `~/.cognee/logs/`、项目进度在 `.cognee-obsidian/`、文件指纹又在 `.deep-obsidian/`——三个地方、两套体系，排查问题时跳来跳去。
3. **静默降级**：search 的后端异常被 `except Exception: return []` 静默吞掉，LLM 的错误被裸 `except Exception` 捕获。用户以为"没找到"，但实际是后端挂了。违反了"快速失败"原则。

## Solution

三管齐下：

1. **惰性导入**：`deep-obsidian` 包级别不 import Cognee，只在命令真正需要时才触发。`--help` 和 `--version` 从此永远干净。
2. **统一日志目录**：所有日志（deep-obsidian 自身 + Cognee 后端）写入 `.deep-obsidian/logs/`，项目级优先，找不到时回退 `~/.deep-obsidian/` 并告警。
3. **异常区分**：search 的 Cognee 异常直接传播，query 的 LLM 异常只对瞬态错误降级，配置/认证错误让用户感知。

## User Stories

### 日志体系

1. As a 用户，I want 所有 deep-obsidian 相关日志统一在 `.deep-obsidian/logs/` 下，so that 排查问题时只看一个地方。
2. As a 用户，I want Cognee 后端的日志也写入 `.deep-obsidian/logs/cognee/`，so that 不使用两套日志体系。
3. As a 用户，I want 日志文件自动滚动（5MB × 3），so that 不会无限增长占用磁盘。
4. As a 用户，I want 日志通过 `settings.json` 中的 `logging.file_level` 和 `logging.console_level` 可配置，so that 我可以按需调整。
5. As a 用户，I want 控制台默认只显示 WARNING 及以上，so that 正常运行时不被打扰。
6. As a 开发者，I want 代码中使用 `get_logger()` 统一获取日志器，so that 日志模块可替换。
7. As a 用户，I want CLI 启动时自动从 cwd 向上查找 `.deep-obsidian/`，so that 在项目的任何子目录下运行都正确记录日志。
8. As a 用户，I want 未找到 `.deep-obsidian/` 时看到 stderr 警告 + 提示 `deep-obsidian init`，so that 我知道环境未正确配置。
9. As a 用户，I want 未初始化时日志回退到 `~/.deep-obsidian/logs/`（不阻塞运行），so that 不影响基本功能。

### CLI 静默

1. As a 用户，I want `deep-obsidian --help` 只显示帮助信息，so that 不被后端日志污染。
2. As a 用户，I want `deep-obsidian --version` 只显示版本号，so that 脚本可以可靠解析。
3. As a 开发者，I want 日志抑制通过 `LOG_LEVEL=ERROR` 环境变量实现，so that 不使用 `sys.stderr` 全局劫持。

### CLI 功能完整性

1. As a 用户，I want `search` 命令支持 `--tag`、`--linked-to`、`--linked-from`、`--date-from`、`--date-to`、`--source` 过滤，so that 所有 Python API 能力都可从命令行使用。

### 错误处理

1. As a 用户，I want 后端错误直接显示而非返回空结果，so that 我能感知并处理问题。
2. As a 用户，I want LLM 临时不可用时 query 能降级显示原始检索结果，so that 我不至于完全得不到信息。
3. As a 用户，I want LLM 配置错误（错误的 API key / 模型名）时直接报错，so that 我能及时修复配置。
4. As a 用户，I want `status()` 在未实现时返回说明性的占位信息而非抛异常，so that CLI 命令不会崩溃。

## Implementation Decisions

### 惰性导入（PEP 562）

`__init__.py` 使用 `__getattr__` 延迟加载子模块（ingest、search、forget、status）。`import deep_obsidian` 不再触发 Cognee 初始化。只有当代码访问 `deep_obsidian.search` 等属性时才实际 import。

这是实现 CLI 静默的基础——Click 装饰器扫描 `main` 函数时触发 `from deep_obsidian import __version__`，但不触发子模块导入。

### 统一日志目录

```
.deep-obsidian/logs/
├── deep-obsidian.log          # deep-obsidian 自身（RotatingFileHandler，5MB×3）
└── cognee/                    # Cognee 后端
    └── 2026-08-04_12-00-00.log
```

- `deep-obsidian.log`：Python `logging` 模块，格式化纯文本。文件级别默认 INFO，控制台默认 WARNING。
- `cognee/`：通过 `COGNEE_LOGS_DIR` 环境变量在 Cognee 初始化前设置。

### settings.json 扩展

新增 `logging` 字段（`init_project()` 自动写入默认值）：

```json
{
  "logging": {
    "file_level": "INFO",
    "console_level": "WARNING"
  }
}
```

### 调试模式

单一入口 `DEEP_OBSIDIAN_DEBUG=1`：

- 控制台 handler 设为 DEBUG（而非 WARNING）
- 跳过 `LOG_LEVEL=ERROR` 设置（Cognee structlog 恢复到默认 INFO）
- `--debug` CLI flag 保留用于 Click 内部的 verbose 模式

### 项目查找策略

`find_project_root(path)` 从 `path` 向上查找 `.deep-obsidian/` 目录，返回最近匹配的父目录。日志模块复用此函数：

- 找到 → `.deep-obsidian/logs/` 写入
- 未找到 → stderr 警告 + 回退 `~/.deep-obsidian/logs/`

### 异常处理规范

| 模块 | 异常类型 | 处理方式 |
|------|---------|---------|
| `search` | 所有 Cognee 异常 | **直接传播**——空结果和错误不能混淆 |
| `query` LLM | `APIConnectionError` / `Timeout` / `ServiceUnavailableError` / `RateLimitError` | 降级：返回原始检索片段 + 说明 |
| `query` LLM | `AuthenticationError` / 其他 `APIError` | **传播**——配置错误需用户修复 |
| `status` | — | 返回占位 dict，不抛异常 |

### 日志模块接口

```python
# 初始化（在 Cognee import 前调用一次）
setup_logging(project_root: Path | None = None, *, debug: bool = False) -> Logger

# 运行时获取
get_logger() -> Logger  # 未初始化时抛 RuntimeError
```

`setup_logging` 必须在任何 Cognee import 之前调用（在 `cli.py` 模块级执行），原因：

1. 设置 `COGNEE_LOGS_DIR` 环境变量
2. Cognee 的 `setup_logging()` 在 import 时读取此变量

## Testing Decisions

### 测试原则

- 只测试公共 API 外部行为
- 单元测试不 import Cognee（毫秒级）
- 集成测试 mock LLM（`cognee.api.v1.cognify.cognify`）

### 新增/修改测试

| 模块 | 测试类型 | 验证点 |
|------|---------|--------|
| `logging_config` | 单元 | `setup_logging` 创建日志文件、handler 配置、`COGNEE_LOGS_DIR` 设置、未初始化时 `get_logger()` 抛 RuntimeError |
| `logging_config` | 单元 | 项目查找：找到 `.deep-obsidian/` 时用项目路径、未找到时回退 `~/.deep-obsidian/` |
| `settings` | 单元 | `init_project` 写入正确的 `logging` 默认值 |
| `status` | 单元 | 返回值结构 `{"dataset", "status", "message"}` |
| `search` | 集成 | Cognee 异常直接传播（不做 `return []`） |
| `query` | 集成 | 瞬态异常降级、认证异常传播 |
| CLI `search` | 集成 | 6 个过滤选项正确传递到 Python API |
| CLI smoke | 集成 | `--help` / `--version` stderr 不含 structlog 输出 |

### 已有测试资产（不变）

- `tests/unit/test_wikilinks.py` — 12
- `tests/unit/test_frontmatter.py` — 10
- `tests/unit/test_tags.py` — 11
- `tests/unit/test_scanner.py` — 9
- `tests/unit/test_progress.py` — 7
- `tests/unit/test_health.py` — 5
- `tests/unit/test_settings.py` — 13
- `tests/integration/test_ingest.py` — 6
- `tests/integration/test_search.py` — 3
- `tests/integration/test_filters.py` — 3

## Out of Scope

- 多日志通道（如 syslog、HTTP endpoint）——当前仅文件 + 控制台
- 日志级别热重载——需重启 CLI
- Cognee 日志格式控制——Cognee 的 structlog 由其自身管理
- `--debug` CLI flag 与 Python logging 的深度集成——当前仅影响 Click verbose 模式

## Further Notes

- Cognee 有 `_is_structlog_configured` 全局标志，首次 import 后不再重新配置。因此 `COGNEE_LOGS_DIR` 必须在首次 import 前设置。
- `find_project_root` 在 `logging_config.py` 和命令函数中各自调用——不在模块间共享状态，保证纯函数特性。
- `.cognee-obsidian/` 已加入 `.gitignore`（progress.json 是运行时产物，不应提交）。
