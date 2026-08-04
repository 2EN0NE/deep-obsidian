# 日志体系

## 总览

deep-obsidian 的日志分为两层，统一存放在 `.deep-obsidian/logs/` 下：

```
.deep-obsidian/logs/
├── deep-obsidian.log          # deep-obsidian 自身日志（滚动）
└── cognee/                    # Cognee 后端日志
    └── 2026-08-04_12-00-00.log
```

| 层 | 负责者 | 技术 | 默认控制台行为 | 文件 |
|----|--------|------|--------------|------|
| **中间层** | deep-obsidian | Python `logging` | WARNING+ → stderr | `.deep-obsidian/logs/deep-obsidian.log`（滚动，5MB×3） |
| **后端层** | Cognee | structlog | 静默（`LOG_LEVEL=ERROR`） | `.deep-obsidian/logs/cognee/`（自动轮转） |

## 配置

日志行为通过 `settings.json` 中的 `logging` 字段控制（`deep-obsidian init` 时自动生成）：

```json
{
  "logging": {
    "file_level": "INFO",
    "console_level": "WARNING"
  }
}
```

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `file_level` | `"INFO"` | 写入日志文件的最低级别 |
| `console_level` | `"WARNING"` | 输出到 stderr 的最低级别 |

支持的级别：`DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`。

## 项目查找

- CLI 启动时自动从当前目录向上查找 `.deep-obsidian/`
- 找到 → 日志写入 `<项目根>/.deep-obsidian/logs/`
- 未找到 → 打印 stderr 警告 + 回退到 `~/.deep-obsidian/logs/`

## 调试模式

```bash
# 开启调试：控制台显示 DEBUG 级别，Cognee 日志也显示
DEEP_OBSIDIAN_DEBUG=1 deep-obsidian search "测试"

# 单独控制 Cognee 日志级别（覆盖默认的 ERROR 抑制）
LOG_LEVEL=INFO deep-obsidian search "测试"
```

`DEEP_OBSIDIAN_DEBUG=1` 的效果：

- 控制台 handler 设为 `DEBUG`（而非 `WARNING`）
- 不再设置 `LOG_LEVEL=ERROR`（Cognee 的 structlog 恢复到默认 INFO 级别）

## Cognee 日志

Cognee 的日志路径由 `COGNEE_LOGS_DIR` 环境变量控制。`setup_logging()` 自动将其设为 `.deep-obsidian/logs/cognee/`，使 Cognee 日志文件统一到项目目录下。

用户可以覆盖：

```bash
COGNEE_LOGS_DIR=/tmp/cognee-debug deep-obsidian ingest ~/vault
```

Cognee 文件日志始终完整写入（无论控制台是否静默）。

## 架构

```
deep-obsidian CLI 进程
│
├─ cli.py 模块级
│   ├─ DEEP_OBSIDIAN_DEBUG? → 若是，跳过 LOG_LEVEL=ERROR
│   ├─ setup_logging() → Python logging 配置 + COGNEE_LOGS_DIR 设置
│   └─ import click + deep_obsidian（惰性导入，不触发 Cognee）
│
├─ 命令执行（如 search）
│   ├─ 惰性导入触发 import cognee
│   │   └─ cognee.setup_logging() 读取
│   │       ├─ LOG_LEVEL → 控制台输出级别
│   │       └─ COGNEE_LOGS_DIR → 日志文件路径
│   └─ deep-obsidian 自身日志
│       └─ logging.getLogger("deep_obsidian")
│           ├─ FileHandler → .deep-obsidian/logs/deep-obsidian.log
│           └─ StreamHandler(stderr) → 控制台
```

## 在代码中使用日志

```python
from deep_obsidian.logging_config import get_logger

_log = get_logger()

_log.debug("详细调试信息")
_log.info("入库进度：%d/%d", done, total)
_log.warning("LLM 响应超时，使用降级策略")
_log.error("数据库连接失败：%s", exc)
```
