"""Ingest pipeline — scan vault, extract metadata, feed Cognee.

Uses the two-phase add+cognify pattern: ``cognee.add()`` writes data and
returns a data_id, then ``cognee.cognify()`` builds the graph in one batch.
Modified files use ``cognee.update()`` (delete-then-re-add).
"""

from __future__ import annotations

import os
import time
import uuid as _uuid
from collections.abc import Callable
from pathlib import Path

import cognee
from cognee.tasks.ingestion.data_item import DataItem

from deep_obsidian.config import inject_config
from deep_obsidian.extractors.frontmatter import parse as parse_frontmatter
from deep_obsidian.extractors.tags import parse as parse_tags
from deep_obsidian.extractors.wikilinks import parse as parse_wikilinks
from deep_obsidian.ingest._fingerprint import file_hash, load_hashes, save_hashes
from deep_obsidian.ingest._health import clear_ladybug_lock
from deep_obsidian.ingest._progress_state import acquire as _acquire_progress
from deep_obsidian.ingest._scanner import scan_vault
from deep_obsidian.settings import LEVEL_USER, resolve_config


class _LLMDegradedWarning(Exception):  # noqa: N818 -- pre-existing name, kept as-is (not touched by this change)
    """Raised when LLM is unavailable but structural ingestion succeeded."""


# ── public API ──


async def ingest(
    vault_path: str | Path,
    *,
    dataset: str | None = None,
    full: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_cognify_start: Callable[[], None] | None = None,
    config_path: str | Path | None = None,
) -> dict:
    """Ingest a Markdown vault into Cognee's knowledge graph.

    Returns:
        dict with keys: total, added, modified, deleted, unchanged, failed,
        elapsed_seconds, warnings
    """
    vault = Path(vault_path).resolve()
    if not vault.exists():
        raise FileNotFoundError(f"Path does not exist: {vault_path}")

    # 配置层级解析（ADR-0014）：--config（显式）> 项目级（从 vault 或 cwd
    # 向上找 .deep-obsidian/）> 用户级 ~/.deep-obsidian（必需基础层）。
    # vault 只用于定位 .cognee 数据与 hashes 状态。
    resolved = resolve_config(vault=vault, cwd=Path.cwd(), config_path=config_path)
    dataset_name = dataset or resolved.settings["name"]

    # Determine files to ingest
    if vault.is_file():
        if vault.suffix != ".md":
            raise ValueError(f"Not a markdown file: {vault_path}")
        current_files: list[Path] = [vault]
    elif vault.is_dir():
        current_files = [vault / f for f in scan_vault(str(vault))]
    else:
        raise NotADirectoryError(f"Not a directory: {vault_path}")

    hashes_path = resolved.hashes_path

    # Load stored hashes (v2 format with data_id).  Always load — even in
    # --full mode — so that files that were already indexed go through
    # cognee.update() and reuse their existing data_id instead of add()
    # with a freshly generated one. Discarding stored hashes on --full
    # would make every already-indexed file look "new", re-adding it
    # under a different data_id and duplicating it in Cognee's graph
    # (the exact bug class ADR-0005 exists to prevent) — and would also
    # hide genuinely deleted files from cleanup. ``full`` only means
    # "don't skip files whose hash is unchanged".
    stored_hashes: dict[str, dict] = load_hashes(str(hashes_path))

    t_start = time.monotonic()

    if not current_files and not stored_hashes:
        return {
            "total": 0,
            "added": 0,
            "modified": 0,
            "deleted": 0,
            "unchanged": 0,
            "failed": 0,
            "elapsed_seconds": time.monotonic() - t_start,
        }

    # ── classify files ──
    current_relpaths = {str(fp.relative_to(resolved.vault)) for fp in current_files}
    stored_relpaths = set(stored_hashes.keys())

    # Files present on disk
    to_process: list[tuple[Path, str, str]] = []  # (filepath, rel, action)
    # action: "add" | "update" | "skip"

    added_count = 0
    modified_count = 0
    unchanged_count = 0
    deleted_count = 0
    failed_count = 0
    all_warnings: list[str] = []

    for idx, filepath in enumerate(current_files):
        rel = str(filepath.relative_to(resolved.vault))
        current_hash = file_hash(str(filepath))
        stored_entry = stored_hashes.get(rel)

        if stored_entry is None:
            # New file
            to_process.append((filepath, rel, "add"))
        elif not full and stored_entry.get("hash") == current_hash:
            unchanged_count += 1
            if on_progress:
                on_progress(idx + 1, len(current_files), f"{rel} (skipped)")
        else:
            # Hash changed, or --full forces reprocessing of an already
            # indexed file — route through update() so its existing
            # data_id is reused instead of minted fresh via add().
            to_process.append((filepath, rel, "update"))

    # Files deleted (identify now, process after Cognee init)
    deleted_rels = stored_relpaths - current_relpaths

    # Remove deleted entries from persisted hashes
    new_hashes = {rel: entry for rel, entry in stored_hashes.items() if rel in current_relpaths}

    total = len(to_process)
    deleted_count = len(deleted_rels)

    # ── Stale-hashes guard ──
    # When every file looks "unchanged" per stored hashes, verify the
    # dataset actually exists in Cognee before returning early.  Without
    # this check, a stale hashes.json — from a venv rebuild, database
    # wipe, or cloned repo — silently blocks all ingestion: the files
    # appear up-to-date by hash, but the data never reached Cognee.
    if unchanged_count > 0 and total == 0 and deleted_count == 0:
        clear_ladybug_lock(str(resolved.vault))
        os.environ.setdefault("TELEMETRY_DISABLED", "1")
        inject_config(resolved)
        cognee.config.data_root_directory(str(resolved.vault / ".cognee"))
        cognee.config.system_root_directory(str(resolved.vault / ".cognee"))
        try:
            ds_list = await cognee.datasets.list_datasets()
            if any(d.name == dataset_name for d in ds_list):
                save_hashes(str(hashes_path), new_hashes)
                return {
                    "total": 0,
                    "added": 0,
                    "modified": 0,
                    "deleted": 0,
                    "unchanged": unchanged_count,
                    "failed": 0,
                    "elapsed_seconds": time.monotonic() - t_start,
                }
        except Exception as _exc:
            all_warnings.append(f"Could not verify dataset existence: {_exc}")

        # Dataset missing or verification failed — hashes are stale.
        all_warnings.append(
            f"Dataset '{dataset_name}' not found in Cognee; "
            f"forcing full re-ingestion (hashes.json may be stale)"
        )
        new_hashes = {}
        to_process = [(fp, str(fp.relative_to(resolved.vault)), "add") for fp in current_files]
        total = len(to_process)
        unchanged_count = 0
        # Fall through — Cognee is already initialized below.

    if total == 0 and deleted_count == 0:
        save_hashes(str(hashes_path), new_hashes)
        return {
            "total": 0,
            "added": 0,
            "modified": 0,
            "deleted": 0,
            "unchanged": unchanged_count,
            "failed": 0,
            "elapsed_seconds": time.monotonic() - t_start,
        }

    # Only initialize Cognee when we know there's actual work to do.
    # Setting data_root_directory spawns the kuzu worker process, so we
    # defer it past the early-return path to avoid unnecessary startup.
    # (Exception: the stale-hashes guard above may have already
    # initialised Cognee; clear_ladybug_lock and config assignments are
    # idempotent, so the block below is harmless in that case.)
    #
    # Both data_root_directory AND system_root_directory must be set —
    # data_root_directory only relocates raw ingested-file storage;
    # the actual graph/vector/relational databases that recall() reads
    # from live under system_root_directory, which otherwise defaults to
    # a fixed, machine/venv-wide location shared by every dataset ever
    # processed there (defeating per-vault isolation — see AGENTS.md
    # "④ 数据跟 Vault 走").
    #
    # The progress/lock handle wraps all of this: it's the cross-process
    # observability + single-instance lock for this run (SPEC-003 /
    # ADR-0009). Acquired only here, past the "nothing to do" early
    # returns above, so a no-op ingest (all unchanged) never touches the
    # lock file. ``acquire()`` raises IngestAlreadyRunningError if
    # another live ingest already holds it for this project — callers
    # (CLI, service) are responsible for presenting that error usefully.
    with _acquire_progress(
        resolved.config_dir,
        dataset_name,
        total,
        vault=resolved.vault if resolved.level == LEVEL_USER else None,
    ) as handle:
        clear_ladybug_lock(str(resolved.vault))
        os.environ.setdefault("TELEMETRY_DISABLED", "1")
        inject_config(resolved)
        cognee.config.data_root_directory(str(resolved.vault / ".cognee"))
        cognee.config.system_root_directory(str(resolved.vault / ".cognee"))

        # Process deleted files (requires Cognee)
        for rel in deleted_rels:
            entry = stored_hashes.get(rel, {})
            data_id = entry.get("data_id")
            if data_id:
                try:
                    await _forget_one(data_id, dataset_name)
                except Exception as e:
                    all_warnings.append(f"Failed to forget deleted file {rel}: {e}")

        # ── Phase 1: Add / update files ──
        dataset_id_for_updates: str | None = None
        pending_cognify = False

        for i, (filepath, rel, action) in enumerate(to_process):
            pre_data_id: str | None = None
            try:
                if action == "add":
                    # Generate data_id before calling add so it survives
                    # _LLMDegradedWarning — structural data is preserved.
                    pre_data_id = str(_uuid.uuid4())
                    ds_id = await _add_one(filepath, dataset_name, data_id=pre_data_id)
                    if ds_id and dataset_id_for_updates is None:
                        dataset_id_for_updates = ds_id
                    new_hashes[rel] = {"hash": file_hash(str(filepath)), "data_id": pre_data_id}
                    added_count += 1
                    pending_cognify = True
                    save_hashes(str(hashes_path), new_hashes)
                    handle.update(phase="adding", current=i + 1, total=total, current_file=rel)
                    if on_progress:
                        on_progress(i + 1, total, f"{rel} (added)")
                elif action == "update":
                    stored_data_id: str | None = stored_hashes.get(rel, {}).get("data_id")
                    if stored_data_id:
                        # Resolve dataset UUID lazily
                        if dataset_id_for_updates is None:
                            dataset_id_for_updates = await _resolve_dataset_id(dataset_name)
                        await _update_one(filepath, stored_data_id, dataset_id_for_updates)
                        new_hashes[rel] = {
                            "hash": file_hash(str(filepath)),
                            "data_id": stored_data_id,
                        }
                        modified_count += 1
                        save_hashes(str(hashes_path), new_hashes)
                        handle.update(phase="adding", current=i + 1, total=total, current_file=rel)
                        if on_progress:
                            on_progress(i + 1, total, f"{rel} (modified)")
                    else:
                        # No data_id — treat as add (old format upgrade path)
                        pre_data_id = str(_uuid.uuid4())
                        await _add_one(filepath, dataset_name, data_id=pre_data_id)
                        new_hashes[rel] = {"hash": file_hash(str(filepath)), "data_id": pre_data_id}
                        added_count += 1
                        pending_cognify = True
                        save_hashes(str(hashes_path), new_hashes)
                        handle.update(phase="adding", current=i + 1, total=total, current_file=rel)
                        if on_progress:
                            on_progress(i + 1, total, f"{rel} (added, no data_id)")
            except _LLMDegradedWarning as e:
                all_warnings.append(str(e))
                if action == "update":
                    modified_count += 1
                    sid = stored_hashes.get(rel, {}).get("data_id")
                    entry: dict = {"hash": file_hash(str(filepath))}
                    if sid:
                        entry["data_id"] = sid
                    new_hashes[rel] = entry
                else:
                    # add — structural data preserved; data_id was generated before the call
                    added_count += 1
                    pending_cognify = True
                    new_hashes[rel] = {"hash": file_hash(str(filepath)), "data_id": pre_data_id}
                save_hashes(str(hashes_path), new_hashes)
                handle.update(phase="adding", current=i + 1, total=total, current_file=rel)
            except Exception as e:
                failed_count += 1
                handle.update(phase="adding", current=i + 1, total=total, current_file=rel)
                if on_progress:
                    on_progress(i + 1, total, f"{rel} FAILED: {e}")

        # Final save is a no-op if the loop already persisted every entry,
        # but keeps behavior correct if to_process was empty (deleted-only run).
        save_hashes(str(hashes_path), new_hashes)

        # ── Phase 2: Batch cognify ──
        if pending_cognify:
            # cognee.cognify() is an opaque batch call with no per-item
            # progress hook (ADR-0009) — the lock can only report that
            # this phase has started, not a percentage.
            handle.update(phase="cognify", current=total, total=total, current_file="")
            if on_cognify_start:
                on_cognify_start()
            try:
                await cognee.cognify(datasets=[dataset_name])
            except cognee.exceptions.CogneeTransientError as e:
                all_warnings.append(f"LLM unavailable during cognify: {e!s}")
            except Exception as e:
                all_warnings.append(f"Cognify failed: {e!s}")

    return {
        "total": total + deleted_count,
        "added": added_count,
        "modified": modified_count,
        "deleted": deleted_count,
        "unchanged": unchanged_count,
        "failed": failed_count,
        "warnings": all_warnings,
        "elapsed_seconds": time.monotonic() - t_start,
    }


# ── internal ──


def _build_data_item(filepath: Path, data_id: str) -> DataItem:
    """Build a DataItem with extracted metadata."""
    text = filepath.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    wikilinks = parse_wikilinks(text)
    tags = parse_tags(text)

    return DataItem(
        data=text,
        data_id=_uuid.UUID(data_id),
        label=filepath.stem,
        external_metadata={
            "file_path": str(filepath),
            "file_name": filepath.name,
            "frontmatter": _json_safe(fm),
            "wikilinks": wikilinks,
            "tags": tags,
        },
    )


def _json_safe(obj):
    """Recursively convert *obj* to a JSON-serializable equivalent.

    PyYAML may parse date-like strings (``2024-01-01``) as
    ``datetime.date`` objects, which ``json.dumps`` cannot handle.
    Cognee stores ``external_metadata`` in a JSON column, so we must
    convert these before handing them off.
    """
    from datetime import date, datetime

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


async def _add_one(filepath: Path, dataset_name: str, data_id: str) -> str | None:
    """Add a single file via ``cognee.add()``, return dataset_id or None."""
    item = _build_data_item(filepath, data_id)
    try:
        result = await cognee.add(item, dataset_name=dataset_name)
    except cognee.exceptions.CogneeTransientError as e:
        msg = str(e)
        raise _LLMDegradedWarning(f"LLM unavailable for {filepath.name}: {msg[:120]}")
    ds_id = None
    if isinstance(result, dict):
        ds_id = result.get("dataset_id")
    elif hasattr(result, "dataset_id"):
        ds_id = result.dataset_id
    return str(ds_id) if ds_id else None


async def _update_one(filepath: Path, data_id: str, dataset_id: str) -> None:
    """Update an existing file via ``cognee.update()``."""
    item = _build_data_item(filepath, data_id)
    try:
        await cognee.update(
            data_id=_uuid.UUID(data_id),
            data=item,
            dataset_id=_uuid.UUID(dataset_id),
        )
    except cognee.exceptions.CogneeTransientError as e:
        msg = str(e)
        raise _LLMDegradedWarning(f"LLM unavailable for {filepath.name}: {msg[:120]}")


async def _forget_one(data_id: str, dataset_name: str) -> None:
    """Forget a single file's data from Cognee."""
    # cognee.forget()'s keyword is ``dataset``, not ``dataset_name`` — it has
    # no **kwargs catch-all, so the wrong name raises TypeError against the
    # real API (verified against cognee==1.4.1). Keep this in sync with
    # forget.py, which calls the same function with the correct kwarg.
    await cognee.forget(data_id=data_id, dataset=dataset_name)


async def _resolve_dataset_id(dataset_name: str) -> str:
    """Resolve a dataset name to its UUID via the public Cognee API."""
    datasets = await cognee.datasets.list_datasets()
    for ds in datasets:
        if getattr(ds, "name", "") == dataset_name:
            return str(ds.id)
    raise RuntimeError(f"Could not resolve dataset UUID for '{dataset_name}'")
