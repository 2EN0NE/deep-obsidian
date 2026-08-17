"""Entry point for ``python -m deep_obsidian.service <config_dir>``.

The parent process (``service start``) passes the resolved config dir
(.deep-obsidian/).  The daemon rebuilds the ResolvedConfig from the
config dir: project level → vault is the config dir's parent.

User level is intentionally NOT reverse-looked-up here: the daemon is a
single-vault long-running process, and a user-level config dir
(~/.deep-obsidian/) maps to many possible vaults.  ``service start``
guards against user-level configs (see cli.py) and ``-m`` with a
user-level config dir exits with a hint — BEFORE importing cognee, so
the reject path stays fast and never touches the network.
"""

import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python -m deep_obsidian.service <config_dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    config_dir = Path(sys.argv[1]).resolve()

    # 纯路径层面的守卫（在任何 deep_obsidian / cognee import 之前）：
    # 用户级 ~/.deep-obsidian 对应对个可能的 vault，反推 vault 只会得到
    # $HOME——绝不允许把 $HOME 当作 vault 全量入库（曾真实发生的回归）。
    if config_dir == Path.home().resolve() / ".deep-obsidian":
        print(
            f"Error: {config_dir} 是用户级配置目录（~/.deep-obsidian），"
            "守护进程无法从中确定唯一的 vault。请传入项目配置目录 "
            "（<vault>/.deep-obsidian）。",
            file=sys.stderr,
        )
        sys.exit(1)

    import asyncio

    from deep_obsidian.service import run_service
    from deep_obsidian.settings import resolve_config

    # 项目级：config_dir 是 <vault>/.deep-obsidian → vault 是其 parent。
    if config_dir.name == ".deep-obsidian" and (config_dir / "settings.jsonc").is_file():
        vault = config_dir.parent
        resolved = resolve_config(vault=vault, cwd=Path.cwd())
        asyncio.run(run_service(resolved))
    else:
        print(
            f"Error: cannot infer vault from config dir {config_dir} "
            "(user-level service requires an explicit --vault).",
            file=sys.stderr,
        )
        sys.exit(1)
