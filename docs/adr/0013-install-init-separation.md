# 安装职责分离：install.sh 管环境与依赖，`deep-obsidian init` 管配置引导

目标用户是小白（非开发者），安装流程有 5 个摩擦点：手动装 Python/uv/git、
`uv sync --dev` 装了不需要的开发依赖、LLM 配置靠 `export` 关终端即丢、
`.env` 存在但代码不读、安装后不引导 service。

我们决定把安装拆成两个职责明确的环节：

1. **`install.sh`（shell）**——只管把代码和环境装到"能执行 `deep-obsidian`"
   的状态：环境检测（Python 3.11+ / uv / git）→ 缺什么给明确命令让用户确认
   后执行（不静默装，不推荐编译 Python 之类的高危操作）→ `uv sync`（不加
   `--dev`）→ 验证 `deep-obsidian --help` 可用。
2. **`deep-obsidian init`（Python/Click）**——交互式配置引导：读已有
   settings.jsonc 预填，回车继承；无 TTY 时 fallback 非交互模式；写
   settings.jsonc；末尾提示"先小批量 ingest → search/query 验证 → 再
   service start"。

**约定：**

- `install.sh` 幂等：`.venv/` 已存在则走修复式重装（每次 `uv sync`，uv 有
  锁文件、已最新时秒级返回），`--reset` 才删 `.venv/` 重建。
- `install.sh` 可观测：全程日志写 `logs/install.log`（带时间戳），终端显示
  精简进度；`--check` 模式只跑环境检测输出 JSON，供 pytest 黑盒测试与用户
  自检。
- 引导逻辑放 Python 而非 bash：可测试、可维护、可复用 provider 分支逻辑。
- 交互式引导只在 TTY 下启用，非 TTY（脚本/CI）fallback 到非交互。
- 平台范围：macOS first，脚本结构预留三端扩展点（Linux/Windows 后续追加）。

**考虑过的替代方案：**

- install.sh 内嵌全部交互引导：bash 写交互逻辑难测难维护，且配置引导与
  `init` 的职责重叠，否决。
- install.sh 每次检测 pyproject.toml 哈希决定是否 uv sync：增加持久化状态
  复杂度，uv 本身幂等，没必要，否决。
- 缺 Python 时静默自动安装：装 Python 是全局操作，用户应知情，否决。

**后果：** README 的安装章节重写为"git clone → ./install.sh → deep-obsidian
init"；`install.sh --check` 输出成为测试与排障的稳定接口；`.env` 相关文档
（USER_GUIDE 的 LLM 配置章节）改为指向 init 引导与 settings.jsonc。
