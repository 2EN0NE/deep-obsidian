#!/usr/bin/env python3
"""Generate or validate the CLI command reference section in README.md.

Usage:
  uv run python scripts/gen_cli_docs.py           # Update README.md in-place
  uv run python scripts/gen_cli_docs.py --check   # Exit non-zero if README is stale
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

import click
from click.types import Choice, IntParamType
from click.types import Path as ClickPath

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MARKER_START = "<!-- CLI-REF-START -->"
MARKER_END = "<!-- CLI-REF-END -->"


def _fmt_opts(param: click.Option) -> str:
    """Render option flags e.g. ``--dir``, ``--force, -f``."""
    opts = sorted(param.opts, key=lambda o: (len(o), o))  # short before long
    return ", ".join(f"`{o}`" for o in opts)


def _fmt_type(param: click.Parameter) -> str:
    """Human-readable type label."""
    if isinstance(param, click.Option) and param.is_flag:
        return "flag"
    ptype = param.type
    if isinstance(ptype, IntParamType):
        return "INT"
    if isinstance(ptype, ClickPath):
        return "PATH"
    if isinstance(ptype, Choice):
        return " | ".join(ptype.choices)
    return "TEXT"


def _fmt_default(param: click.Parameter) -> str:
    """Default value label."""
    if isinstance(param, click.Option) and param.is_flag:
        return "false" if param.default is None or param.default is False else "true"
    # Check for Click's internal UNSET sentinel (no default set).
    if type(param.default).__name__ == "Sentinel":
        return "—"
    return str(param.default)


def _short_help(cmd: click.Command) -> str:
    """Get the short help text: short_help → docstring first line → fallback."""
    sh = cmd.short_help
    if sh:
        return sh
    if cmd.help:
        return cmd.help.strip().split("\n")[0].rstrip(".")
    return "(no description)"


def _command_path(cmd: click.Command) -> str:
    """Return the full command path e.g. 'service start'."""
    # Walk parent refs (runtime-only, not in Click's type stubs).
    parts: list[str] = []
    c: click.BaseCommand | None = cmd
    while c is not None:
        if isinstance(c, click.Command):
            parts.append(c.name or "?")
        c = getattr(c, "parent", None)  # type: ignore[assignment]
    return " ".join(reversed(parts))


def extract_commands(cli: click.Group) -> list[tuple[str, click.Command]]:
    """Recursively extract all leaf commands with their full paths."""
    result: list[tuple[str, click.Command]] = []

    def walk(group: click.Group, prefix: str) -> None:
        for name, cmd in group.commands.items():
            full = f"{prefix} {name}".strip()
            if isinstance(cmd, click.Group):
                walk(cmd, full)
            else:
                result.append((full, cmd))

    walk(cli, "")
    return result


def _render_command(cmd_path: str, cmd: click.Command) -> str:
    """Render a single command's documentation block."""
    lines: list[str] = []
    lines.append(f"### `{cmd_path}`")
    lines.append("")
    lines.append(f"{_short_help(cmd)}")
    lines.append("")

    # Collect non-hidden params (hidden attr exists at runtime, not in type stubs)
    params = [p for p in cmd.params if not getattr(p, "hidden", False)]
    arguments = [p for p in params if isinstance(p, click.Argument)]
    options = [p for p in params if isinstance(p, click.Option)]

    if arguments:
        lines.append("**参数：**")
        lines.append("")
        for a in arguments:
            required = "" if a.required else "（可选）"
            help_text = getattr(a, "help", "") or ""
            if help_text:
                lines.append(f"- `{a.human_readable_name}` {required}— {help_text}")
            else:
                # rstrip：无帮助文本时避免尾随空格（markdownlint 会剥离，
                # 导致 --check 误报 drift）。
                lines.append(f"- `{a.human_readable_name}` {required}".rstrip())
        lines.append("")

    if options:
        lines.append("| 选项 | 类型 | 默认 | 说明 |")
        lines.append("|------|------|------|------|")
        for o in options:
            lines.append(
                f"| {_fmt_opts(o)} | {_fmt_type(o)} | {_fmt_default(o)} | {o.help or ''} |"
            )
        lines.append("")

    return "\n".join(lines)


def _render_generic_conventions(cli: click.Group) -> str:
    """Render the common conventions all commands share."""
    # Discover which commands support --json / --vault
    json_cmds: list[str] = []
    vault_cmds: list[str] = []
    for path, cmd in extract_commands(cli):
        for p in cmd.params:
            if isinstance(p, click.Option):
                if p.name == "json_output":
                    json_cmds.append(path)
                if p.name == "vault_path":
                    vault_cmds.append(path)

    lines: list[str] = []
    lines.append("### 通用约定")
    lines.append("")
    lines.append("所有命令都遵守以下规约：")
    lines.append("")

    lines.append("- **`--help`** — 每个命令和子命令都支持 `--help`，显示完整用法和所有可用选项。")
    lines.append("")
    lines.append(
        "- **`--config <file>`** — 全局选项，直接指定 settings.jsonc 路径"
        "（覆盖项目级/用户级自动查找）。所有命令均可携带。"
    )
    lines.append("")

    if json_cmds:
        listed = "、".join(f"`{c}`" for c in json_cmds)
        lines.append(
            f"- **`--json`** — 支持 JSON 输出的命令（{listed}）"
            "统一使用 `--json` 标志，输出单行机器可读 JSON。"
        )
        lines.append("")

    if vault_cmds:
        listed = "、".join(f"`{c}`" for c in vault_cmds)
        lines.append(
            f"- **`--vault <path>`** — 需要指定 vault 目录的命令（{listed}）"
            "统一使用 `--vault`。默认从当前目录向上查找包含"
            " `.deep-obsidian/settings.jsonc` 的目录。"
        )
        lines.append("")

    lines.append(
        "- **位置参数** — `init` 和 `ingest` 的 vault 路径是位置参数"
        "（不是 `--vault`），因为它们是初始化或导入操作，天然需要一个明确的路径。"
    )
    lines.append("")

    return "\n".join(lines)


def generate_section(cli: click.Group) -> str:
    """Generate the full CLI command reference section."""
    parts: list[str] = []
    parts.append(_render_generic_conventions(cli))
    parts.append("### 命令参考")
    parts.append("")

    for path, cmd in extract_commands(cli):
        parts.append(_render_command(path, cmd))

    return "\n".join(parts)


def read_readme() -> str:
    return README.read_text(encoding="utf-8")


def write_readme(content: str) -> None:
    README.write_text(content, encoding="utf-8")


def replace_section(readme: str, generated: str) -> str:
    """Replace the content between MARKER_START and MARKER_END with *generated*."""
    before, _, after_start = readme.partition(MARKER_START + "\n")
    if not after_start:
        print(
            f"Error: marker {MARKER_START} not found in README.md",
            file=sys.stderr,
        )
        sys.exit(1)
    _, _, after_end = after_start.partition("\n" + MARKER_END)
    if not after_end:
        print(
            f"Error: marker {MARKER_END} not found in README.md",
            file=sys.stderr,
        )
        sys.exit(1)

    return before + MARKER_START + "\n\n" + generated + "\n" + MARKER_END + after_end


def main() -> None:
    check_mode = "--check" in sys.argv

    # We can't import deep_obsidian.cli.main at module level because
    # it suppresses Cognee logging; do the import lazily.
    from deep_obsidian.cli import main as cli

    generated = generate_section(cli)
    readme = read_readme()

    generated_section = MARKER_START + "\n\n" + generated + "\n" + MARKER_END

    # Extract current section from README
    before, _, after_start = readme.partition(MARKER_START + "\n")
    if not after_start:
        print(f"Error: marker {MARKER_START} not found in README.md", file=sys.stderr)
        sys.exit(1)
    _, _, after_end = after_start.partition("\n" + MARKER_END)
    existing_section = (
        MARKER_START + "\n" + after_start.partition("\n" + MARKER_END)[0] + "\n" + MARKER_END
    )

    if check_mode:
        if generated_section != existing_section:
            diff = difflib.unified_diff(
                existing_section.splitlines(keepends=True),
                generated_section.splitlines(keepends=True),
                fromfile="README.md (current)",
                tofile="README.md (expected)",
            )
            sys.stdout.writelines(diff)
            print(
                "\nREADME.md CLI reference is stale."
                " Run 'python scripts/gen_cli_docs.py' to update.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("README.md CLI reference is up to date.")
        return
    else:
        if generated_section == existing_section:
            print("README.md CLI reference is already up to date.")
            return
        new_readme = replace_section(readme, generated)
        write_readme(new_readme)
        print("README.md CLI reference updated.")


if __name__ == "__main__":
    main()
