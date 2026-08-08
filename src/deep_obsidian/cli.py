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
@click.version_option(__version__)
def main(debug: bool) -> None:
    """deep-obsidian — search your Obsidian notes with AI."""
    if debug:
        import logging

        _os.environ["DEEP_OBSIDIAN_DEBUG"] = "1"
        # Reconfigure the console handler to DEBUG level.
        # setup_logging() was already called at module level;
        # we locate the StreamHandler and bump its level.
        for h in _log.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setLevel(logging.DEBUG)


@main.command()
@click.argument("path", type=click.Path(file_okay=False), default=".")
@click.option("--name", "-n", help="Project name (default: directory name)")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Reset: delete old .deep-obsidian/, .cognee/, and stale logs before init",
)
def init(path: str, name: str | None, force: bool) -> None:
    """Initialize a deep-obsidian project in PATH.

    Pass --force to wipe all stale state from a previous run and start fresh.
    Use this when README \"init → ingest\" doesn't behave as expected because
    of leftovers from earlier sessions.
    """
    from pathlib import Path as _Path

    from deep_obsidian.settings import init_project

    # Allow --force on a non-existent directory (will be created by init_project)
    _target = _Path(path)
    if not force and not _target.exists():
        raise click.BadParameter(f"Path does not exist: {path}")

    data = init_project(path, name=name, force=force)
    click.echo(f"Initialized project '{data['name']}' ({data['deep-obsidian-id']})")
    click.echo(f"Config: {path}/.deep-obsidian/settings.json")


@main.command()
@click.argument("target", type=click.Path(exists=True))
@click.option("--full", is_flag=True, help="Force full re-ingest")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
def ingest(target: str, full: bool, json_output: bool) -> None:
    """Import markdown files into the knowledge graph.

    TARGET is a vault directory (or a single .md file) that has
    already been through 'deep-obsidian init'.  The dataset name is
    always the project's name in .deep-obsidian/settings.json —
    there is no separate dataset override.
    """
    from pathlib import Path as _Path

    from deep_obsidian.ingest import ingest as do_ingest
    from deep_obsidian.ingest._progress import ProgressCard
    from deep_obsidian.ingest._progress_state import IngestAlreadyRunningError
    from deep_obsidian.ingest._scanner import scan_vault
    from deep_obsidian.settings import find_project_root, read_settings

    vault = _Path(target).resolve()
    vault_name = vault.name
    # Best-effort display name for the progress card — falls back to
    # the folder name if settings can't be read yet (do_ingest() will
    # raise its own clear error for that case).
    try:
        _root = find_project_root(vault)
        ds = read_settings(_root)["name"] if _root else vault_name
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
                return await do_ingest(target, full=full)

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


@main.command()
@click.argument("query")
@click.option(
    "--dir",
    "dir_path",
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
def search(
    query: str,
    dir_path: str | None,
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

    Searches the vault found by walking up from --dir (or the current
    directory if --dir is omitted).  The dataset is always that
    vault's name from .deep-obsidian/settings.json — there is no
    separate dataset override.
    """
    from deep_obsidian.search import search as do_search

    _start = _time.time()

    async def _run():
        return await do_search(
            query,
            vault_path=dir_path,
            top_k=top_k,
            tag=tag,
            linked_to=linked_to,
            linked_from=linked_from,
            date_from=date_from,
            date_to=date_to,
            source=source,
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


@main.command()
@click.argument("question")
@click.option(
    "--dir",
    "dir_path",
    type=click.Path(file_okay=False),
    help="Vault directory to query (default: current directory or an ancestor)",
)
@click.option("--top-k", type=int, default=5, help="Number of search results to use")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
def query(question: str, dir_path: str | None, top_k: int, json_output: bool) -> None:
    """Ask a question and get an AI-synthesized answer with citations."""
    from deep_obsidian.query import query as do_query

    async def _run():
        return await do_query(question, vault_path=dir_path, top_k=top_k)

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


@main.command()
@click.argument("targets", nargs=-1, type=click.Path())
@click.option("--all", "forget_all", is_flag=True, help="Clear the entire dataset")
@click.option(
    "--dir",
    "dir_path",
    type=click.Path(file_okay=False),
    help="Vault directory (default: current directory or an ancestor)",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
def forget(
    targets: tuple[str, ...],
    forget_all: bool,
    dir_path: str | None,
    yes: bool,
    json_output: bool,
) -> None:
    """Delete indexed files from the knowledge graph.

    TARGETS are file paths, directory paths, or absolute paths to forget.
    Use --all to delete the entire dataset.
    """
    from deep_obsidian.forget import forget as do_forget
    from deep_obsidian.ingest._fingerprint import load_hashes
    from deep_obsidian.settings import find_project_root

    root = find_project_root(Path(dir_path) if dir_path else Path.cwd())
    hashes_path = str(root / ".deep-obsidian" / "hashes.json") if root else None

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
        if not yes and root and hashes_path:
            from deep_obsidian.forget import _match_target

            indexed = {
                rel: e.get("data_id")
                for rel, e in load_hashes(hashes_path).items()
                if e.get("data_id")
            }
            all_matched: list[str] = []
            for t in targets:
                matched, _reason = _match_target(t, indexed, root)
                all_matched.extend(matched)
            if len(all_matched) > 1:
                click.echo(f"This will forget {len(all_matched)} files:")
                for m in sorted(all_matched):
                    click.echo(f"  {m}")
                click.echo("Proceed? [y/N] ", nl=False)
                if input().strip().lower() != "y":
                    click.echo("Cancelled.")
                    _sys.exit(0)
            elif len(all_matched) == 0:
                # Nothing matched — let forget() handle the warnings
                pass
            # Single file: no confirmation (handled implicitly by pass)

    async def _run():
        return await do_forget(
            list(targets) if targets else None,
            all=forget_all,
            vault_path=dir_path,
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


@main.command(name="status")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
def status_cmd(json_output: bool) -> None:
    """Show whether an ingest is currently running for this project.

    One-shot snapshot of the current ingest run state (idle / running /
    stale) — not to be confused with 'service status', which reports
    whether the background file-watching daemon is alive.
    """
    from deep_obsidian.ingest._progress import _format_time
    from deep_obsidian.status import status as do_status

    async def _run():
        return await do_status()

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


@main.group()
def service() -> None:
    """Manage file-watching service (start, status, stop)."""


@service.command()
def start() -> None:
    """Start watching for file changes."""
    from deep_obsidian.service import start_service
    from deep_obsidian.settings import find_project_root

    root = find_project_root(Path.cwd())
    if root is None:
        click.echo(
            "Error: Not in a deep-obsidian project. Run 'deep-obsidian init' first.",
            err=True,
        )
        _sys.exit(1)

    try:
        pid = start_service(root)
        click.echo(f"Service started (PID: {pid})")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)


@service.command()
def status() -> None:
    """Show service status."""
    from deep_obsidian.service import service_status
    from deep_obsidian.settings import find_project_root

    root = find_project_root(Path.cwd())
    if root is None:
        click.echo("Error: Not in a deep-obsidian project.", err=True)
        _sys.exit(1)

    st = service_status(root)
    if st["status"] == "running":
        click.echo(f"Service is running (PID: {st['pid']})")
    elif st["status"] == "stale_pid":
        click.echo(f"Service appears dead (stale PID file, PID: {st['pid']})")
    else:
        click.echo("Service is stopped.")


@service.command()
def stop() -> None:
    """Stop the file-watching service."""
    from deep_obsidian.service import stop_service
    from deep_obsidian.settings import find_project_root

    root = find_project_root(Path.cwd())
    if root is None:
        click.echo("Error: Not in a deep-obsidian project.", err=True)
        _sys.exit(1)

    if stop_service(root):
        click.echo("Service stopped.")
    else:
        click.echo("Service was not running.")


if __name__ == "__main__":
    main()
