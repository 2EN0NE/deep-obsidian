"""Ingest pipeline — scan vault, extract metadata, feed Cognee."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import cognee
from cognee.tasks.ingestion.data_item import DataItem

from deep_obsidian.extractors.frontmatter import parse as parse_frontmatter
from deep_obsidian.extractors.tags import parse as parse_tags
from deep_obsidian.extractors.wikilinks import parse as parse_wikilinks
from deep_obsidian.ingest._fingerprint import file_hash, load_hashes, save_hashes
from deep_obsidian.ingest._health import clear_ladybug_lock
from deep_obsidian.ingest._progress import ProgressStore
from deep_obsidian.ingest._scanner import scan_vault
from deep_obsidian.settings import find_project_root, read_settings


class _LLMDegradedWarning(Exception):
    """Raised when LLM is unavailable but structural ingestion succeeded."""


async def ingest(
    vault_path: str | Path,
    *,
    dataset: str | None = None,
    full: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Ingest a Markdown vault into Cognee's knowledge graph.

    Returns:
        dict with keys: total, success, failed, skipped, elapsed_seconds
    """
    vault = Path(vault_path).resolve()
    if not vault.exists():
        raise FileNotFoundError(f"Path does not exist: {vault_path}")

    # Find project root and load settings
    project_root = find_project_root(vault)
    if project_root is None:
        raise RuntimeError(
            "No .deep-obsidian/ directory found. "
            "Run 'deep-obsidian init' first in the project root."
        )
    _settings = read_settings(project_root)
    dataset = dataset or _settings["name"]

    # Determine files to ingest
    if vault.is_file():
        if vault.suffix != ".md":
            raise ValueError(f"Not a markdown file: {vault_path}")
        filepaths: list[Path] = [vault]
    elif vault.is_dir():
        filepaths = [vault / f for f in scan_vault(str(vault))]
    else:
        raise NotADirectoryError(f"Not a directory: {vault_path}")
    progress_path = project_root / ".cognee-obsidian" / "progress.json"
    hashes_path = project_root / ".deep-obsidian" / "hashes.json"
    progress = ProgressStore(str(progress_path))

    # Load stored file hashes for incremental comparison
    stored_hashes: dict[str, str] = {} if full else load_hashes(str(hashes_path))
    new_hashes: dict[str, str] = {}

    t_start = time.monotonic()

    # Health: clear stale Ladybug lock before touching Cognee
    clear_ladybug_lock(str(project_root))

    # Set Cognee data root to project-local
    cognee.config.data_root_directory = str(project_root / ".cognee")
    if not filepaths:
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "elapsed_seconds": time.monotonic() - t_start,
        }

    total = len(filepaths)
    success, failed, skipped = 0, 0, 0
    all_warnings: list[str] = []

    for i, filepath in enumerate(filepaths):
        rel = str(filepath.relative_to(project_root))
        current_hash = file_hash(str(filepath))

        # Skip if unchanged (only in incremental mode)
        if not full and stored_hashes.get(rel) == current_hash:
            skipped += 1
            new_hashes[rel] = current_hash
            if on_progress:
                on_progress(i + 1, total, f"{rel} (skipped)")
            continue

        try:
            await _ingest_one(filepath, dataset)
            success += 1
            progress.mark_done(rel)
            new_hashes[rel] = current_hash
            if on_progress:
                on_progress(i + 1, total, rel)
        except _LLMDegradedWarning as e:
            # Structural data stored, but LLM cognify failed
            all_warnings.append(str(e))
            success += 1
            progress.mark_done(rel)
            new_hashes[rel] = current_hash
        except Exception as e:
            failed += 1
            if on_progress:
                on_progress(i + 1, total, f"{rel} FAILED: {e}")

    # Persist hashes for next incremental run
    save_hashes(str(hashes_path), new_hashes)

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "warnings": all_warnings,
        "elapsed_seconds": time.monotonic() - t_start,
    }


async def _ingest_one(filepath: Path, dataset: str) -> dict:
    """Ingest a single file. Returns warnings dict if LLM issues."""
    warnings = []
    text = filepath.read_text(encoding="utf-8")

    fm = parse_frontmatter(text)
    wikilinks = parse_wikilinks(text)
    tags = parse_tags(text)

    item = DataItem(
        data=text,
        label=filepath.stem,
        external_metadata={
            "file_path": str(filepath),
            "file_name": filepath.name,
            "frontmatter": fm,
            "wikilinks": wikilinks,
            "tags": tags,
        },
    )

    try:
        await cognee.remember(item, dataset_name=dataset)
    except cognee.exceptions.CogneeTransientError as e:
        # Network / timeout / overload — recoverable.  Structural data
        # (wikilinks, tags, frontmatter) was passed via external_metadata
        # and should have been persisted.
        msg = str(e)
        warnings.append(f"LLM unavailable for {filepath.name}: {msg[:120]}")
        raise _LLMDegradedWarning(warnings[0])
    # Config / auth / system errors propagate as hard failures — they
    # need user action (fix API key, correct model name, etc.) and
    # will never self-heal.

    return {"warnings": warnings}
