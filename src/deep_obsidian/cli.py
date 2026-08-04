"""CLI entry point — deep-obsidian command.

Quiet by default: Cognee's import-time logging is suppressed via
LOG_LEVEL=ERROR.  Set ``DEEP_OBSIDIAN_DEBUG=1`` or pass ``--debug``
to see verbose output.
"""

from __future__ import annotations

import asyncio
import json
import os as _os
import sys as _sys

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
@click.argument("path", type=click.Path(exists=True, file_okay=False), default=".")
@click.option("--name", "-n", help="Project name (default: directory name)")
def init(path: str, name: str | None) -> None:
    """Initialize a deep-obsidian project in PATH."""
    from deep_obsidian.settings import init_project

    data = init_project(path, name=name)
    click.echo(f"Initialized project '{data['name']}' ({data['deep-obsidian-id']})")
    click.echo(f"Config: {path}/.deep-obsidian/settings.json")


@main.command()
@click.argument("target", type=click.Path(exists=True))
@click.option("--dataset", "-d", help="Dataset name (default: from settings)")
@click.option("--full", is_flag=True, help="Force full re-ingest")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
def ingest(target: str, dataset: str | None, full: bool, json_output: bool) -> None:
    """Import markdown files into the knowledge graph."""
    from deep_obsidian.ingest import ingest as do_ingest

    async def _run():
        return await do_ingest(target, dataset=dataset, full=full)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
    elif result["total"] == 0:
        click.echo("No markdown files found.")
    else:
        click.echo(
            f"Ingested {result['success']}/{result['total']} files "
            f"({result['skipped']} skipped, {result['failed']} failed) "
            f"in {result['elapsed_seconds']:.1f}s"
        )
        for w in result.get("warnings", []):
            click.echo(f"  ⚠️  {w}")


@main.command()
@click.argument("query")
@click.option("--dataset", "-d", help="Dataset to search")
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
    dataset: str | None,
    top_k: int,
    tag: str | None,
    linked_to: str | None,
    linked_from: str | None,
    date_from: str | None,
    date_to: str | None,
    source: str | None,
    json_output: bool,
) -> None:
    """Search the knowledge graph (no LLM processing)."""
    from deep_obsidian.search import search as do_search

    async def _run():
        return await do_search(
            query,
            dataset=dataset,
            top_k=top_k,
            tag=tag,
            linked_to=linked_to,
            linked_from=linked_from,
            date_from=date_from,
            date_to=date_to,
            source=source,
        )

    try:
        results = asyncio.run(_run())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if json_output:
        click.echo(json.dumps(results, ensure_ascii=False, default=str))
    elif not results:
        click.echo("No results found.")
    else:
        for i, r in enumerate(results, 1):
            label = r.get("label", "") or r.get("content", "")[:60].replace("\n", " ")
            layer = r.get("layer", "?")
            src = r.get("source_file", "?")
            click.echo(f"[{i}] {label} ({layer}, {src})")


@main.command()
@click.argument("question")
@click.option("--dataset", "-d", help="Dataset to search")
@click.option("--top-k", type=int, default=5, help="Number of search results to use")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
def query(question: str, dataset: str | None, top_k: int, json_output: bool) -> None:
    """Ask a question and get an AI-synthesized answer with citations."""
    from deep_obsidian.query import query as do_query

    async def _run():
        return await do_query(question, dataset=dataset, top_k=top_k)

    try:
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
@click.option("--dataset", "-d", help="Dataset to forget (default: from settings)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output")
def forget(dataset: str | None, yes: bool, json_output: bool) -> None:
    """Delete the current project's knowledge graph data."""
    from deep_obsidian.forget import forget as do_forget

    if not yes:
        click.echo("Permanently delete knowledge graph data? [y/N] ", nl=False)
        if input().strip().lower() != "y":
            click.echo("Cancelled.")
            _sys.exit(0)

    async def _run():
        return await do_forget(dataset=dataset)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        _sys.exit(1)

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
    else:
        click.echo(f"Dataset '{result['dataset']}' forgotten.")


@main.group()
def service() -> None:
    """Manage file-watching service (start, status, stop)."""


@service.command()
def start() -> None:
    """Start watching for file changes."""
    click.echo("Service not yet implemented.")


@service.command()
def status() -> None:
    """Show service status."""
    click.echo("Service not running.")


@service.command()
def stop() -> None:
    """Stop the file-watching service."""
    click.echo("Service stopped.")


if __name__ == "__main__":
    main()
