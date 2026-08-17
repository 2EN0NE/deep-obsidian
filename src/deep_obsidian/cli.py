"""CLI entry point — deep-obsidian command.

Quiet by default: Cognee's import-time logging is suppressed via
LOG_LEVEL=ERROR.  Set ``DEEP_OBSIDIAN_DEBUG=1`` or pass ``--debug``
to see verbose output.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os as _os
import sys as _sys
import time as _time
from pathlib import Path

# ── Suppress Cognee's noisy import-time logging ──
# Performed early (before any Cognee module is imported) so that the
# structlog configuration inside cognee.shared.logging_utils reads
# LOG_LEVEL from the environment.  Users can override with
# ``DEEP_OBSIDIAN_DEBUG=1`` or by setting ``LOG_LEVEL`` themselves.
if not _os.environ.get("DEEP_OBSIDIAN_DEBUG"):
    _os.environ.setdefault("LOG_LEVEL", "ERROR")

# ── Init logging (before Cognee import) ──
from deep_obsidian.logging_config import setup_logging

_log = setup_logging(debug=bool(_os.environ.get("DEEP_OBSIDIAN_DEBUG")))

import click  # noqa: E402

from deep_obsidian import __version__  # noqa: E402


@contextlib.contextmanager
def _quiet_stdout_when_json(json_output: bool):
    """Redirect stray stdout noise to stderr while --json is active.

    Cognee's own Alembic migration checks ("X table already exists,
    skipping creation") use bare ``print()`` rather than logging, so
    they bypass LOG_LEVEL entirely and land on real stdout. Left
    alone, that noise precedes and corrupts the single JSON line
    --json callers expect to parse. Only active for --json since
    human-readable output tolerates the extra lines fine.
    """
    if not json_output:
        yield
        return
    with contextlib.redirect_stdout(_sys.stderr):
        yield


def _describe_lock_conflict(e) -> str:
    """Render an ``IngestAlreadyRunningError`` as a friendly one-liner
    including how long the lock holder has been running.
    """
    state = e.state
    elapsed = ""
    started_at = state.get("started_at")
    if isinstance(started_at, (int, float)):
        from deep_obsidian.ingest._progress import _format_time

        elapsed = f", running for {_format_time(_time.time() - started_at)}"
    return (
        f"Another ingest is already running for dataset '{state.get('dataset')}' "
        f"(PID {state.get('pid')}, phase: {state.get('phase')}{elapsed})."
    )


@click.group()
@click.option("--debug", is_flag=True, help="Show verbose debug output")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    help="Explicit settings.jsonc path (overrides project/user lookup)",
)
@click.version_option(__version__)
@click.pass_context
def main(ctx: click.Context, debug: bool, config_path: str | None) -> None:
    """deep-obsidian — search your Obsidian notes with AI."""
    ctx.obj = {"config_path": config_path}
    if debug:
        import logging

        _os.environ["DEEP_OBSIDIAN_DEBUG"] = "1"
        # Reconfigure the console handler to DEBUG level.
        # setup_logging() was already called at module level;
        # we locate the StreamHandler and bump its level.
        for h in _log.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setLevel(logging.DEBUG)


def _is_tty() -> bool:
    """Whether stdin is an interactive terminal.

    Tests can force interactive mode via DEEP_OBSIDIAN_INTERACTIVE=1.
    """
    if _os.environ.get("DEEP_OBSIDIAN_INTERACTIVE") == "1":
        return True
    return _sys.stdin.isatty()


def _prompt_default(prompt: str, default: str | None, password: bool = False) -> str:
    """交互式输入：有默认值显示在提示里，回车继承。"""
    if password:
        # 密码类输入不回显默认值（API key 不应出现在屏幕/日志里），
        # 仅提示可回车继承。
        suffix = "（回车保留当前值）" if default else ""
    elif default:
        suffix = f" [{default}]"
    else:
        suffix = ""
    if password:
        value = click.prompt(
            f"{prompt}{suffix}",
            default=default or "",
            hide_input=True,
            show_default=False,
        )
    else:
        value = click.prompt(f"{prompt}{suffix}", default=default or "", show_default=False)
    return value.strip()


# LLM provider 分支：provider 决定问哪些字段、默认值是什么。
# 每个条目: (provider_id, 显示名, {字段: 默认值})
_LLM_PROVIDERS = [
    ("openai", "OpenAI 官方", {"model": "openai/gpt-5-mini", "api_key": "", "endpoint": ""}),
    (
        "custom",
        "自定义 / 代理 (DeepSeek 等)",
        {"model": "openai/deepseek-v4-pro", "api_key": "", "endpoint": ""},
    ),
    (
        "ollama",
        "Ollama 本地",
        {"model": "ollama/llama3.1:8b", "api_key": "", "endpoint": "http://localhost:11434"},
    ),
]


def _ask_llm_config(existing: dict) -> dict:
    """交互式问 LLM 配置，返回 {provider, model, api_key, endpoint}。

    ``existing`` 是已有 settings 的 llm 段（可能是空 dict）。
    用户回车继承已有值；无已有值时用 provider 默认。
    """
    # Provider 菜单
    cur_provider = existing.get("provider", "openai")
    click.echo("\n[1/3] LLM 配置（用于语义推理）")
    click.echo("  请选择 LLM 服务商：")
    for idx, (pid, label, _d) in enumerate(_LLM_PROVIDERS, 1):
        mark = " *" if pid == cur_provider else ""
        click.echo(f"    {idx}. {label}{mark}")
    choice = click.prompt(
        "  选择 (1-3)",
        type=click.IntRange(1, len(_LLM_PROVIDERS)),
        default=next(
            (i for i, (pid, _l, _d) in enumerate(_LLM_PROVIDERS, 1) if pid == cur_provider),
            1,
        ),
    )
    pid, _label, defaults = _LLM_PROVIDERS[choice - 1]

    # 按 provider 分支问字段（已有配置预填）
    model = _prompt_default("  Model", existing.get("model") or defaults.get("model", ""))
    api_key = _prompt_default("  API Key", existing.get("api_key") or "", password=True)
    endpoint = _prompt_default(
        "  Endpoint", existing.get("endpoint") or defaults.get("endpoint", "")
    )
    return {"provider": pid, "model": model, "api_key": api_key, "endpoint": endpoint}


def _ask_embedding_config(existing: dict) -> dict:
    """交互式问 Embedding 配置（默认 fastembed，回车跳过）。"""
    click.echo("\n[2/3] Embedding 配置（向量嵌入，默认 fastembed 本地）")
    provider = _prompt_default("  Provider", existing.get("provider") or "fastembed")
    model = _prompt_default("  Model", existing.get("model") or "BAAI/bge-small-en-v1.5")
    fallback = existing.get("dimensions") or 384
    dims_raw = _prompt_default("  Dimensions", str(fallback))
    try:
        dimensions = int(dims_raw)
    except ValueError:
        # 静默回退会让维度与模型不匹配的问题延迟到 ingest/search 才
        # 以隐晦错误暴露——明确告知用户。
        click.echo(f"  ⚠️  无效的 Dimensions 输入 '{dims_raw}'，已使用当前值 {fallback}", err=True)
        dimensions = fallback
    return {"provider": provider, "model": model, "dimensions": dimensions}


def _ask_network_config(existing: dict) -> dict:
    """交互式问网络配置（可选，回车跳过）。

    默认 hf_hub_offline=false —— 首次 ingest 需联网下载 embedding 模型
    （~100MB，缓存到 ~/.cache/huggingface/），下载完成后可在这里开启完全
    离线（修复：模板默认曾为 true，导致新用户首次 ingest 被离线模式阻止）。
    """
    click.echo("\n[3/3] 网络配置（可选，HuggingFace 镜像等，回车跳过）")
    hf = _prompt_default("  HF_ENDPOINT 镜像", existing.get("hf_endpoint") or "")
    offline = click.confirm(
        "  HF 完全离线模式（模型下载完成后建议开启）",
        default=bool(existing.get("hf_hub_offline")),
    )
    return {"hf_endpoint": hf, "hf_hub_offline": offline}


def _interactive_init(project_root: Path, existing: dict, effective: dict | None = None) -> dict:
    """交互式配置引导：问 LLM/Embedding/Network，返回完整更新。

    ``existing`` 是当前层级的现有配置；``effective`` 是三级 merge 后的有效
    配置（ADR-0014）——预填默认值以 effective 为准：项目级留空继承用户级的
    值（如 hf_hub_offline=true、embedding dimensions）时，向导显示继承后的
    有效值，回车不会写出显式默认值静默覆盖更低层级。

    api_key 例外：保持层级本地预填——项目级留空继承用户级 key 时，回车
    继续写空串（merge 时继承生效），避免把共享 key 物化进层级配置文件。
    """
    prefill = effective or existing
    # llm 段：有效值 + 层级本地 api_key（见 docstring）。
    llm_prefill = dict(prefill.get("llm") or {})
    llm_prefill["api_key"] = (existing.get("llm") or {}).get("api_key") or ""
    click.echo(f"\n正在配置项目 '{prefill.get('name', project_root.name)}' ...")
    click.echo("（直接回车 = 保留当前值 / 使用默认值）")

    llm = _ask_llm_config(llm_prefill)
    embedding = _ask_embedding_config(prefill.get("embedding", {}))
    network = _ask_network_config(prefill.get("network", {}))

    return {"llm": llm, "embedding": embedding, "network": network}


@main.command(short_help="初始化 deep-obsidian 项目。")
@click.argument(
    "path",
    type=click.Path(file_okay=False),
    required=False,
)
@click.option("--name", "-n", help="Project name (default: directory name)")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Reset: delete stale .deep-obsidian/ and .cognee/ before init"
    "（注意：用户级 --force 会删除整个 ~/.deep-obsidian/）",
)
def init(path: str | None, name: str | None, force: bool) -> None:
    """Initialize a deep-obsidian project in PATH.

    Interactive flow (TTY): choose config level (project default / user)
    → vault path → LLM/Embedding/Network prompts.  Non-TTY: defaults to
    project level with the given PATH.

    Pass --force to wipe all stale state from a previous run and start fresh.
    """
    from deep_obsidian.settings import (
        LEVEL_PROJECT,
        LEVEL_USER,
        init_project,
        read_settings,
        update_settings,
    )

    # ── 混合模式：PATH 给了就用，没给则交互式问（仅 TTY）──
    _target: Path
    if path is not None:
        _target = Path(path)
        if not force and not _target.exists():
            raise click.BadParameter(f"Path does not exist: {path}")
    elif _is_tty():
        _target = Path(click.prompt("Vault 路径", type=click.Path(file_okay=False, exists=True)))
    else:
        raise click.BadParameter(
            "init 需要指定 PATH（非交互环境无法询问 vault 路径）。"
            "用法: deep-obsidian init <vault-path>"
        )

    # ── 层级选择（ADR-0014）：默认项目级；用户级兼建保证 merge 基础层 ──
    level = LEVEL_PROJECT
    also_user = False
    if _is_tty():
        level_choice = click.prompt(
            "配置层级： [1] 项目级（默认） / [2] 用户级",
            type=click.Choice(["1", "2"], case_sensitive=False),
            default="1",
            show_default=False,
        )
        if level_choice.strip() == "2":
            level = LEVEL_USER
        # 用户级是必需基础层——默认兼建（除非已有）
        user_cfg = Path.home() / ".deep-obsidian" / "settings.jsonc"
        if level == LEVEL_PROJECT and not user_cfg.is_file():
            also_user = click.confirm("是否同时创建用户级共享配置？（默认是）", default=True)
    elif not (Path.home() / ".deep-obsidian" / "settings.jsonc").is_file():
        # 非交互：默认兼建用户级（ADR-0014 必需基础层）
        also_user = True
        level = LEVEL_PROJECT

    # 已存在配置时读取现有（用于交互预填）；不存在则为空
    existing = {}
    try:
        existing = read_settings(_target if level == LEVEL_PROJECT else Path.home())
    except Exception:
        existing = {}

    # 用户级 --force 是破坏性操作：init_project 会删除整个 ~/.deep-obsidian/
    # （含所有 vault 的 hashes.json、index.json 映射与 progress 锁）以及
    # <vault>/.cognee/（该 vault 的知识图谱）——必须执行前显式警告。
    if level == LEVEL_USER and force:
        click.echo(
            "⚠️  即将执行用户级 --force：将删除 ~/.deep-obsidian/（含全部 vault 的"
            f"增量状态与注册表）以及 {_target}/.cognee/（该 vault 的知识图谱）。",
            err=True,
        )

    data = init_project(_target, name=name, force=force, level=level)
    if also_user and level == LEVEL_PROJECT:
        init_project(_target, name=name, force=False, level=LEVEL_USER)

    # ── 交互式引导（TTY 下）──
    if _is_tty():
        # 预填默认值用 merge 后的有效配置：此时三级层级已就绪（含刚兼建的
        # 用户级），项目级留空继承的用户级值（hf_hub_offline、dimensions 等）
        # 在向导中显示为有效值，回车不会写出显式默认覆盖它（修复：曾只看
        # 单层配置，把继承的 hf_hub_offline=true 静默改成 false）。解析失败
        # （如用户拒绝了兼建用户级）时退回单层现有配置。
        effective = existing
        try:
            from deep_obsidian.settings import resolve_config

            effective = resolve_config(vault=_target, cwd=Path.cwd()).settings
        except Exception:
            pass
        updates = _interactive_init(_target, existing, effective)
        target_root = _target if level == LEVEL_PROJECT else Path.home()
        try:
            update_settings(target_root, updates)
        except ValueError as e:
            # update_jsonc 无法安全改写文件时（如单行内联对象）大声失败，
            # 不静默写入与用户意图不符的配置。
            click.echo(f"Error: {e}", err=True)
            _sys.exit(1)
        data = read_settings(target_root)

    config_label = (
        "~/.deep-obsidian/settings.jsonc"
        if level == LEVEL_USER
        else (f"{_target}/.deep-obsidian/settings.jsonc")
    )
    click.echo(f"Initialized project '{data['name']}' ({data['deep-obsidian-id']})")
    click.echo(f"Config: {config_label}")

    # ── 下一步提示 ──
    click.echo("\n下一步：")
    click.echo(f"  1. 导入笔记:  deep-obsidian ingest {_target}")
    click.echo(f'  2. 搜索:      deep-obsidian search "你的问题" --vault {_target}')
    click.echo(f'  3. 问答:      deep-obsidian query "你的问题" --vault {_target}')
    click.echo("  建议先小批量 ingest 验证 search/query 可用后，再运行：")
    click.echo("    deep-obsidian service start   # 后台文件监控")

    # ── 旧配置文件迁移警告（ADR-0011：.env 与 settings.json 已退役）──
    legacy_env = _target / ".env"
    legacy_json = _target / ".deep-obsidian" / "settings.json"
    if legacy_env.is_file() or legacy_json.is_file():
        click.echo("\n⚠️  检测到旧配置文件（已退役格式）：", err=True)
        if legacy_env.is_file():
            click.echo("  - .env （请删除，配置已迁移到 settings.jsonc）", err=True)
        if legacy_json.is_file():
            click.echo(
                "  - .deep-obsidian/settings.json （请删除，配置已迁移到 settings.jsonc）",
                err=True,
            )


@main.command(short_help="将 Markdown 文件导入知识图谱。")
@click.argument("target", type=click.Path(exists=True))
@click.option("--full", is_flag=True, help="Force full re-ingest")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
@click.pass_context
def ingest(ctx: click.Context, target: str, full: bool, json_output: bool) -> None:
    """Import markdown files into the knowledge graph.

    TARGET is a vault directory (or a single .md file) that has
    already been through 'deep-obsidian init'.  The dataset name is
    the merged config name (ADR-0014) — no separate dataset override.
    """
    from pathlib import Path as _Path

    from deep_obsidian.ingest import ingest as do_ingest
    from deep_obsidian.ingest._progress import ProgressCard
    from deep_obsidian.ingest._progress_state import IngestAlreadyRunningError
    from deep_obsidian.ingest._scanner import scan_vault
    from deep_obsidian.settings import resolve_config

    vault = _Path(target).resolve()
    vault_name = vault.name
    # Best-effort display name for the progress card — falls back to
    # the folder name if settings can't be read yet (do_ingest() will
    # raise its own clear error for that case).
    try:
        _resolved = resolve_config(vault=vault, config_path=ctx.obj["config_path"])
        ds = _resolved.settings["name"]
    except Exception:
        ds = vault_name

    # Count files for the scan phase (fast – just os.walk)
    if not json_output and _sys.stderr.isatty():
        card = ProgressCard(vault_name, ds)
        _result: dict | None = None
        try:
            md_files = scan_vault(str(vault)) if vault.is_dir() else [str(vault)]
            card.start_scan(len(md_files))

            def _on_progress(current: int, total: int, desc: str) -> None:
                card.update(current, total, desc)

            def _on_cognify_start() -> None:
                card.start_cognify()

            try:
                _result = asyncio.run(
                    do_ingest(
                        target,
                        full=full,
                        on_progress=_on_progress,
                        on_cognify_start=_on_cognify_start,
                        config_path=ctx.obj["config_path"],
                    )
                )
            except KeyboardInterrupt:
                click.echo(
                    "\n已中断。已处理的文件进度已保存，重新运行 ingest 可从断点继续。",
                    err=True,
                )
                _sys.exit(130)
            except IngestAlreadyRunningError as e:
                click.echo(f"Error: {_describe_lock_conflict(e)}", err=True)
                _sys.exit(1)
            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                _sys.exit(1)
        finally:
            if _result is not None:
                card.finish(
                    added=_result.get("added", 0),
                    modified=_result.get("modified", 0),
                    skipped=_result.get("unchanged", 0),
                    failed=_result.get("failed", 0),
                )
            else:
                card._clear()
        result: dict = _result  # type: ignore[assignment]
    else:
        try:

            async def _run():
                return await do_ingest(target, full=full, config_path=ctx.obj["config_path"])

            with _quiet_stdout_when_json(json_output):
                result = asyncio.run(_run())
        except KeyboardInterrupt:
            click.echo(
                "已中断。已处理的文件进度已保存，重新运行 ingest 可从断点继续。",
                err=True,
            )
            _sys.exit(130)
        except IngestAlreadyRunningError as e:
            click.echo(f"Error: {_describe_lock_conflict(e)}", err=True)
            _sys.exit(1)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            _sys.exit(1)

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
    elif result["total"] == 0 and result.get("unchanged", 0) == 0 and result.get("deleted", 0) == 0:
        click.echo("No markdown files found.")
    else:
        parts = []
        if result.get("added"):
            parts.append(f"{result['added']} added")
        if result.get("modified"):
            parts.append(f"{result['modified']} modified")
        if result.get("deleted"):
            parts.append(f"{result['deleted']} deleted")
        if result.get("unchanged"):
            parts.append(f"{result['unchanged']} unchanged")
        if result.get("failed"):
            parts.append(f"{result['failed']} failed")
        summary = ", ".join(parts)
        click.echo(f"Ingested ({summary}) in {result['elapsed_seconds']:.1f}s")
        for w in result.get("warnings", []):
            click.echo(f"  ⚠️  {w}")


@main.command(short_help="检索知识图谱（不经 LLM 加工）。")
@click.argument("query")  # help via docstring
@click.option(
    "--vault",
    "vault_path",
    type=click.Path(file_okay=False),
    help="Vault directory to search (default: current directory or an ancestor)",
)
@click.option("--top-k", type=int, default=5, help="Number of results")
@click.option("--tag", help="Filter by tag")
@click.option("--linked-to", help="Filter: notes that link TO this note")
@click.option("--linked-from", help="Filter: notes linked FROM this note")
@click.option("--date-from", help="Filter: notes dated on or after YYYY-MM-DD")
@click.option("--date-to", help="Filter: notes dated on or before YYYY-MM-DD")
@click.option("--source", help="Filter by source file path")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    vault_path: str | None,
    top_k: int,
    tag: str | None,
    linked_to: str | None,
    linked_from: str | None,
    date_from: str | None,
    date_to: str | None,
    source: str | None,
    json_output: bool,
) -> None:
    """Search the knowledge graph (no LLM processing).

    Searches the vault found by walking up from --vault (or the current
    directory if --vault is omitted).  The dataset is the merged config
    name (ADR-0014) — no separate dataset override.
    """
    from deep_obsidian.search import search as do_search

    _start = _time.time()

    async def _run():
        return await do_search(
            query,
            vault_path=vault_path,
            top_k=top_k,
            tag=tag,
            linked_to=linked_to,
            linked_from=linked_from,
            date_from=date_from,
            date_to=date_to,
            source=source,
            config_path=ctx.obj["config_path"],
        )

    try:
        with _quiet_stdout_when_json(json_output):
            results = asyncio.run(_run())
        elapsed = _time.time() - _start
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if json_output:
        results_with_meta = {
            "results": results,
            "elapsed": round(elapsed, 4),
            "count": len(results),
        }
        click.echo(json.dumps(results_with_meta, ensure_ascii=False, default=str))
    elif not results:
        click.echo("No results found.")
    else:
        for i, r in enumerate(results, 1):
            label = r.get("label", "") or r.get("content", "")[:60].replace("\n", " ")
            content = r.get("content", "")
            match_type = r.get("match_type", "?")
            src = r.get("source_file", "?")
            click.echo(f"[{i}] {label}")
            if content:
                # Indent and wrap the snippet for readability.
                lines = content.strip().split("\n")
                for line in lines[:10]:  # Cap at 10 lines — chunks are short anyway
                    click.echo(f"    | {line}")
            click.echo(f"    @ {src}  ({match_type})")
        click.echo(f"\n搜索耗时 {elapsed:.2f}s，共 {len(results)} 条结果")


@main.command(short_help="提问并获得 AI 合成的答案（含引用来源）。")
@click.argument("question")  # help via docstring
@click.option(
    "--vault",
    "vault_path",
    type=click.Path(file_okay=False),
    help="Vault directory to query (default: current directory or an ancestor)",
)
@click.option("--top-k", type=int, default=5, help="Number of search results to use")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
@click.pass_context
def query(
    ctx: click.Context,
    question: str,
    vault_path: str | None,
    top_k: int,
    json_output: bool,
) -> None:
    """Ask a question and get an AI-synthesized answer with citations."""
    from deep_obsidian.query import query as do_query

    async def _run():
        return await do_query(
            question, vault_path=vault_path, top_k=top_k, config_path=ctx.obj["config_path"]
        )

    try:
        with _quiet_stdout_when_json(json_output):
            result = asyncio.run(_run())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
    else:
        click.echo(result["answer"])
        if result.get("sources"):
            click.echo("\nSources:")
            for s in result["sources"]:
                click.echo(f"  - {s}")


@main.command(short_help="从知识图谱中删除已索引的文件。")
@click.argument("targets", nargs=-1, type=click.Path())
@click.option("--all", "forget_all", is_flag=True, help="Clear the entire dataset")
@click.option(
    "--vault",
    "vault_path",
    type=click.Path(file_okay=False),
    help="Vault directory (default: current directory or an ancestor)",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
@click.pass_context
def forget(
    ctx: click.Context,
    targets: tuple[str, ...],
    forget_all: bool,
    vault_path: str | None,
    yes: bool,
    json_output: bool,
) -> None:
    """Delete indexed files from the knowledge graph.

    TARGETS are file paths, directory paths, or absolute paths to forget.
    Use --all to delete the entire dataset.
    """
    from deep_obsidian.forget import forget as do_forget
    from deep_obsidian.ingest._fingerprint import load_hashes
    from deep_obsidian.settings import resolve_config

    try:
        resolved = resolve_config(
            vault=Path(vault_path) if vault_path else None,
            config_path=ctx.obj["config_path"],
        )
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)
    hashes_path = str(resolved.hashes_path)

    # ── determine scope for confirmation ──
    if forget_all:
        if targets:
            click.echo("Error: cannot specify both targets and --all.", err=True)
            _sys.exit(1)
        stored = load_hashes(hashes_path) if hashes_path else {}
        count = len(stored)
        if not yes:
            click.echo(f"⚠️  This will clear the ENTIRE knowledge graph ({count} files).")
            click.echo("Proceed? [y/N] ", nl=False)
            if input().strip().lower() != "y":
                click.echo("Cancelled.")
                _sys.exit(0)
    elif not targets:
        click.echo(
            "Error: please specify target files/directories to forget, "
            "or use --all to clear the entire dataset.",
            err=True,
        )
        _sys.exit(1)
    else:
        # File-level: show what will be forgotten
        if not yes:
            from deep_obsidian.forget import _match_target

            indexed = {
                rel: e.get("data_id")
                for rel, e in load_hashes(hashes_path).items()
                if e.get("data_id")
            }
            matched_paths: list[str] = []
            for t in targets:
                matched, _reason = _match_target(t, indexed, resolved.vault)
                matched_paths.extend(matched)
            if len(matched_paths) > 1:
                click.echo(f"This will forget {len(matched_paths)} files:")
                for m in sorted(matched_paths):
                    click.echo(f"  {m}")
                click.echo("Proceed? [y/N] ", nl=False)
                if input().strip().lower() != "y":
                    click.echo("Cancelled.")
                    _sys.exit(0)
            elif len(matched_paths) == 0:
                # Nothing matched — let forget() handle the warnings
                pass
            # Single file: no confirmation (handled implicitly by pass)

    async def _run():
        return await do_forget(
            list(targets) if targets else None,
            all=forget_all,
            vault_path=vault_path,
            config_path=ctx.obj["config_path"],
        )

    try:
        with _quiet_stdout_when_json(json_output):
            result = asyncio.run(_run())
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
    else:
        click.echo(f"Forgotten {result['forgotten']} file(s) from '{result['dataset']}'.")
        for w in result.get("warnings", []):
            click.echo(f"  ⚠️  {w}")


@main.command(name="status", short_help="查看当前是否有 ingest 正在运行。")
@click.option(
    "--vault",
    "vault_path",
    type=click.Path(file_okay=False),
    help="Vault directory (default: current directory or an ancestor)",
)
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
@click.pass_context
def status_cmd(ctx: click.Context, vault_path: str | None, json_output: bool) -> None:
    """Show whether an ingest is currently running for this project.

    One-shot snapshot of the current ingest run state (idle / running /
    stale) — not to be confused with 'service status', which reports
    whether the background file-watching daemon is alive.
    """
    from deep_obsidian.ingest._progress import _format_time
    from deep_obsidian.status import status as do_status

    async def _run():
        return await do_status(vault_path=vault_path, config_path=ctx.obj["config_path"])

    try:
        result = asyncio.run(_run())
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
        return

    st = result["status"]
    if st == "idle":
        click.echo("No ingest is currently running.")
        return

    dataset = result.get("dataset")
    phase = result.get("phase")
    current = result.get("current")
    total = result.get("total")
    current_file = result.get("current_file")
    started_at = result.get("started_at")

    elapsed = ""
    if isinstance(started_at, (int, float)):
        elapsed = f" · elapsed: {_format_time(_time.time() - started_at)}"

    if st == "running":
        parts = [f"Ingesting '{dataset}' — phase: {phase}", f"{current}/{total}"]
        if current_file:
            parts.append(current_file)
        click.echo(" · ".join(parts) + elapsed)
    else:  # stale
        click.echo(
            f"⚠️  Last ingest for '{dataset}' appears to have crashed "
            f"at {phase} ({current}/{total}). Re-run 'deep-obsidian ingest' to continue."
        )


@main.group(short_help="管理用户级 vault 注册（index.json 映射）。")
def vaults() -> None:
    """Manage the user-level vault registry (ADR-0014).

    User-level configs share ~/.deep-obsidian/; each vault's state
    (hashes.json) lives under ~/.deep-obsidian/vaults/<hash>/.  When a
    vault directory moves, its hash changes and the mapping breaks —
    ``relink`` repairs it.
    """


@vaults.command("list", short_help="列出用户级注册的 vault 映射。")
def list_vaults() -> None:
    """List the registered vault → hash mappings."""
    from deep_obsidian.settings import _user_settings_dir, load_vault_index

    user_dir = _user_settings_dir()
    index = load_vault_index(user_dir)
    if not index:
        click.echo("No user-level vaults registered.")
        return
    for h, entry in sorted(index.items()):
        vpath = entry.get("vault_path", "?")
        ds = entry.get("dataset", "?")
        click.echo(f"{h}  →  {vpath}  (dataset: {ds})")


@vaults.command(short_help="重新关联已移动路径的 vault。")
@click.argument("old_path", type=click.Path())
@click.argument("new_path", type=click.Path())
def relink(old_path: str, new_path: str) -> None:
    """Re-point a vault that moved from OLD_PATH to NEW_PATH.

    Updates the registry entry (re-hash) and moves the hashes state
    directory so incremental state survives the move.
    """
    import shutil

    from deep_obsidian.settings import (
        _user_settings_dir,
        load_vault_index,
        register_vault,
        unregister_vault,
        vault_path_hash,
    )

    user_dir = _user_settings_dir()
    old_h = vault_path_hash(Path(old_path).resolve())
    new_h = vault_path_hash(Path(new_path).resolve())
    index = load_vault_index(user_dir)
    entry = index.get(old_h)
    if entry is None:
        click.echo(f"Error: '{old_path}' is not a registered user-level vault.", err=True)
        _sys.exit(1)

    # Move the hashes state dir (if any)
    old_state = user_dir / "vaults" / old_h
    new_state = user_dir / "vaults" / new_h
    if old_state.is_dir() and not new_state.exists():
        try:
            shutil.move(str(old_state), str(new_state))
        except OSError as e:
            click.echo(f"Warning: could not move state dir: {e}", err=True)

    register_vault(user_dir, new_path, dataset=entry.get("dataset"))
    unregister_vault(user_dir, old_path)
    click.echo(f"Re-linked '{old_path}' → '{new_path}'")


@main.group(short_help="管理文件监控后台服务。")
def service() -> None:
    """Manage file-watching service (start, status, stop)."""


@service.command(short_help="启动文件变更监控。")
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start watching for file changes."""
    from deep_obsidian.settings import LEVEL_USER, resolve_config

    try:
        resolved = resolve_config(vault=None, config_path=ctx.obj["config_path"])
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    # 守护进程是长驻单 vault 进程：必须能从 config_dir 反推出唯一的
    # vault（<vault>/.deep-obsidian）。用户级 ~/.deep-obsidian 对应多个
    # vault，无法反推——允许它启动会让守护进程把 $HOME 当作 vault 全量
    # 入库（曾真实发生的回归）。守卫在 import service/cognee 之前，
    # 失败路径不付任何初始化成本。
    if (
        resolved.level == LEVEL_USER
        or resolved.config_dir.name != ".deep-obsidian"
        or resolved.config_dir.parent == Path.home().resolve()
    ):
        click.echo(
            "Error: service 需要在项目目录内启动（当前解析到用户级或非标准配置目录，"
            "无法确定唯一的 vault）。请在项目根目录（含 .deep-obsidian/settings.jsonc）"
            "下运行。",
            err=True,
        )
        _sys.exit(1)

    from deep_obsidian.service import start_service

    try:
        pid = start_service(resolved)
        click.echo(f"Service started (PID: {pid})")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)


@service.command(short_help="查看文件监控守护进程是否存活。")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show service status."""
    from deep_obsidian.service import service_status
    from deep_obsidian.settings import resolve_config

    try:
        resolved = resolve_config(vault=None, config_path=ctx.obj["config_path"])
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    st = service_status(resolved.config_dir)
    if st["status"] == "running":
        click.echo(f"Service is running (PID: {st['pid']})")
    elif st["status"] == "stale_pid":
        click.echo(f"Service appears dead (stale PID file, PID: {st['pid']})")
    else:
        click.echo("Service is stopped.")


@service.command(short_help="停止文件监控服务。")
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Stop the file-watching service."""
    from deep_obsidian.service import stop_service
    from deep_obsidian.settings import resolve_config

    try:
        resolved = resolve_config(vault=None, config_path=ctx.obj["config_path"])
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if stop_service(resolved.config_dir):
        click.echo("Service stopped.")
    else:
        click.echo("Service was not running.")


if __name__ == "__main__":
    main()
