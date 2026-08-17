# CLI 文档从 Click 元数据自动生成，CI 校验一致性

README 的命令参考段过去是手写散文，与 CLI 代码 (`cli.py`) 的命令注册常
不同步——新增命令或选项后 README 经常漏更新。我们决定从 Click 的
`Group.commands` 和 `Parameter` 元数据自动生成命令参考段，CI 用
`--check` 模式拦截不一致。

**约定：**

- 生成脚本 `scripts/gen_cli_docs.py` 就地替换 README 中
  `<!-- CLI-REF-START -->` / `<!-- CLI-REF-END -->` 之间的内容。
- 每个 Click command 必须设置 `short_help` 参数——`--help` 和 README
  命令表共享同一摘要文本。
- CI 的 lint job 运行 `uv run python scripts/gen_cli_docs.py --check`，
  不一致时 exit 1 并输出 diff。
- 本地开发流：改 CLI → `uv run python scripts/gen_cli_docs.py` →
  提交更新后的 README。

**考虑过的替代方案：**

- 纯手动维护（现状）：无法机械校验，漂移频发，否决。
- 全量 README 模板生成：失去叙事灵活性，Quick Start 等人文内容无法模板化，
  否决。
- Click 自省 + 独立 `docs/cli-reference.md`：用户多跳一次，且两个文件间仍
  可能不一致，否决。
