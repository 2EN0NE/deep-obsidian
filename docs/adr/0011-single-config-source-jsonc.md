# 配置单一来源：settings.jsonc 取代 .env 和 settings.json

项目过去有两套配置：`.env`（LLM/Embedding/网络，Cognee 原生读取，但代码从未
`load_dotenv()`，用户手动 `export` 的变量关终端即丢）和
`.deep-obsidian/settings.json`（项目自身：dataset name、id）。两套来源并存
导致小白用户无法理解"配置到底在哪"。

我们决定**全面合并为单一配置文件 `.deep-obsidian/settings.jsonc`**，`.env` 和
`settings.json` 都退役。理由：

- 单一来源是小白用户能理解的心智模型——"所有配置都在一个文件里"。
- JSONC 格式（支持注释和尾逗号）比裸 JSON 友好——小白用户打开文件看到
  `"provider": "custom"` 不知道能填什么，旁边有注释 `// 可选: openai, custom, ollama`
  就不一样了。
- 选择 JSONC 而非 YAML：项目自身配置（`settings.json`）本就是 JSON 系，
  迁移路径最短；YAML 的缩进错误对小白更致命。
- 嵌套结构深度 ≤3 层——超过就说明该重新抽取设计了，避免配置层级失控。

**约定：**

- 文件位于 `.deep-obsidian/settings.jsonc`，`.gitignore` 已忽略 `.deep-obsidian/`，
  API key 不会进版本库。
- 文件头必须有提示注释（"此文件含 API key，勿提交 git"）。
- 解析库用 `json5`（标准 `json5.loads()` API，纯 Python 零依赖，支持注释/尾逗号）。
- `find_project_root()` 的判定条件从"存在 settings.json"改为"存在 settings.jsonc"。

**考虑过的替代方案：**

- 保留 `.env` + 代码加 `load_dotenv()`：两个来源优先级混乱，用户改 jsonc 但被
  .env 覆盖会困惑，否决。
- 用 YAML：缩进敏感，小白易错，否决。
- 项目配置与后端配置分两个文件（settings.json + settings.jsonc）：多文件即
  多困惑，违背单一来源，否决。

**后果：** `settings.py` 全面改造为 jsonc 读写；所有依赖 settings.json 的代码
（ingest/search/forget/status/service 取 dataset name）同步迁移；SPEC 中旧
配置 schema 失效。
