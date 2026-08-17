# 配置三级层级与存储布局：--config / 项目级 / 用户级

`settings.jsonc` 单一配置源（ADR-0011）解决了"配置文件格式"，但没有回答
"配置存在哪"——过去配置只跟项目走（`.deep-obsidian/settings.jsonc`），
`--dir` 参数名义上是操作范围、实际承担配置查找起点，语义混用。且同一台
机器多个 vault 各自维护 LLM API key 是重复劳动。

我们决定引入**三级配置层级 + 深度 merge**，并把状态文件（hashes.json、
`.cognee/`）的存放位置与配置层级分离。

## 配置层级

优先级从高到低：`--config`（显式指定）> 项目级（`.deep-obsidian/settings.jsonc`）> 用户级（`~/.deep-obsidian/settings.jsonc`）。

- **--config 全局参数**：所有命令（ingest/init/search/query/forget/status/service）均可携带，直接指定配置文件路径，不再向上查找。
- **深度 merge**：三个层级的配置按优先级取并集，嵌套键逐键合并。
- **非空才覆盖**：高优先级非空（非 null/空串/缺失）才覆盖低优先级。关键场景：项目级 `api_key` 留空 → 继承用户级 key。
- **用户级是必需基础层**：完整配置（含 name），`init` 默认兼建用户级；运行时若用户级缺失则报错提示先创建。

## 存储布局（与配置层级分离）

- **Cognee 数据库 `.cognee/`**：`<vault>/.cognee/`，**始终跟 vault 走**——删 vault
  即删数据，隔离完整（ADR-0006 红线保持）。
- **项目级状态 hashes.json**：`.deep-obsidian/vault/hashes.json`——一个项目
  = 一个 vault，直接存放。
- **用户级状态 hashes.json**：`~/.deep-obsidian/vaults/<hash>/hashes.json`
  ——多个 vault 共用用户级配置时按 vault 路径 hash 隔离。
- **映射 index.json**：`~/.deep-obsidian/vaults/index.json`（仅在用户级）——记录
  hash → vault 绝对路径 的映射。
- **hashes 内文件路径**：相对 vault 目录，配置来自用户级时语义不混乱。

**Vault 重新关联**：新增 `deep-obsidian vaults relink <旧路径> <新路径>` 子命令，显式修改
index.json 中的映射（vault 目录移动后 hash 失配时使用）。

## 关键取舍

1. **配置与数据分离**：配置可以共享（用户级 API key 全机器通用），但 Cognee
   数据永远跟 vault 走。放弃"删配置目录即删数据"的省事，换取"删 vault 即删
   数据"的隔离确定性。
2. **用户级必需**：不接受"用户级可选"——那会让 merge 行为在有无用户级之间漂移。
   统一要求基础层存在，init 默认兼建。
3. **hashes 相对 vault**：过去相对 project_root（配置目录），配置来自用户级时
   会错乱。改为相对 vault，与 `.cognee/` 的位置基准一致。

## 考虑过的替代方案

- **hashes/.cognee 全部跟配置目录走**（用户级时集中到 `~/.cognee/`）：实现简单但破坏
  ADR-0006 隔离，多 vault 共享数据库靠 dataset 名区分，风险高，否决。
- **用户级可选**：merge 链路在有/无用户级间漂移，行为不一致，否决。
- **浅覆盖**：llm 整块覆盖会丢失"项目级 provider + 用户级 api_key"的组合，否决。
