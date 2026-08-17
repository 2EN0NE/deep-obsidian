# Cognee 配置通过 cognee.config.set_xxx() API 注入，不走环境变量

调研 Cognee 源码（`.venv/.../cognee/infrastructure/llm/config.py`、
`base_config.py`、`api/v1/config/config.py`）确认：

- Cognee 的 `LLMConfig` / `EmbeddingConfig` / `BaseConfig` 都是
  `pydantic_settings.BaseSettings`，实例化时读环境变量 + 工作目录 `.env`，
  且被 `@lru_cache` 缓存——一旦某次调用后环境变量变化，已缓存的配置对象不会
  重读。
- 但 Cognee 提供了完整的运行时 setter API（`cognee.config.set_llm_config({...})`、
  `cognee.config.set_embedding_config({...})`），直接修改已缓存的 config 对象
  属性，不经过环境变量。

我们决定：**deep-obsidian 从 settings.jsonc 读取 LLM/Embedding 配置后，通过
`cognee.config.set_llm_config()` / `set_embedding_config()` 注入**，不再依赖
`.env` 文件，也不再要求用户在 shell 里 `export`。

**约定：**

- settings.jsonc 中 `llm.*` 字段机械映射到 `cognee.config.set_llm_config()` 的
  key（`llm.provider` → `llm_provider`，`llm.model` → `llm_model`，等等）。
- `embedding.*` 同理映射到 `set_embedding_config()`。
- 非 Cognee 的环境变量（`HF_ENDPOINT`、`HF_HUB_OFFLINE`、
  `COGNEE_SKIP_CONNECTION_TEST`）仍通过 `os.environ[...] = ...` 设置——这些
  是运行时库（HuggingFace）在 import 时读的，没有等效 setter。
- 注入必须在触碰任何 Cognee API 之前完成。各集成点（ingest/search/query/
  forget/service）在调用 Cognee 前统一执行注入。

**考虑过的替代方案：**

- 保留 `.env` 让 Cognee 原生读取：项目已决定 `.env` 退役（ADR-0011），且
  `.env` 只在工作目录有效，位置语义模糊，否决。
- `import cognee` 前设置环境变量再让 BaseSettings 读取：需要精确控制 import
  时机，且 `@lru_cache` 之后无法再改，灵活度差，否决。
- 直接把 jsonc 当 Cognee 的 `.env` 用（`SettingsConfigDict(env_file=...)` 指向
  自定义路径）：耦合进 Cognee 的读取机制，版本间行为不稳定，否决。

**后果：** 需要在 `src/deep_obsidian/` 新增一个配置注入模块，所有集成点调用；
`import cognee` 的时机不再敏感（注入可发生在 import 之后、API 调用之前）。
