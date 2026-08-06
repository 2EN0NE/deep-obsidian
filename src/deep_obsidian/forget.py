"""Forget — delete data from the knowledge graph.

Two modes:

* **File-level** — ``forget(["Books/Justice.md"])`` removes specific
  files from the graph, matching by relative path, directory prefix,
  basename, or absolute path.
* **Bulk** — ``forget(all=True)`` clears the entire dataset.

Like ``rm``, file-level forget removes entries from
``.deep-obsidian/hashes.json`` so a subsequent ``ingest`` sees them as
new files and re-adds them.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import cognee

from deep_obsidian.ingest._fingerprint import load_hashes, save_hashes
from deep_obsidian.ingest._health import clear_ladybug_lock
from deep_obsidian.settings import find_project_root, read_settings


async def forget(
    targets: list[str] | None = None,
    *,
    all: bool = False,
    dataset: str | None = None,
    vault_path: str | Path | None = None,
) -> dict:
    """Delete data from the knowledge graph.

    Args:
        targets: List of file/directory/absolute paths to forget.
            If ``None``, ``all`` must be ``True``.
        all: If ``True``, delete the entire dataset.
            Mutually exclusive with ``targets``.
        dataset: Dataset name (default: from settings).
        vault_path: Project root lookup path (default: cwd).

    Returns:
        dict with keys: forgotten, dataset, warnings.
    """
    if targets and all:
        raise ValueError("Cannot specify both targets and --all.")

    if not targets and not all:
        raise ValueError(
            "Please specify target files or directories to forget, "
            "or use --all to clear the entire dataset."
        )

    lookup = Path(vault_path) if vault_path else Path.cwd()
    project_root = find_project_root(lookup)
    if project_root is None:
        raise RuntimeError(
            "No .deep-obsidian/ directory found. "
            "Run 'deep-obsidian init' first in the project root."
        )
    _settings = read_settings(project_root)
    dataset_name = dataset or _settings["name"]
    hashes_path = str(project_root / ".deep-obsidian" / "hashes.json")

    # Initialize Cognee with project-local data directory.
    # Without this, forget() can't find the database and may hang
    # on a stale Ladybug lock from a previous interrupted ingest.
    #
    # Both data_root_directory AND system_root_directory must be set —
    # see the matching comment in ingest/__init__.py for why: only the
    # latter actually relocates the graph/vector/relational databases
    # that forget() operates on, so leaving it unset means every vault
    # on this machine shares (and can delete from) the same database.
    clear_ladybug_lock(str(project_root))
    os.environ.setdefault("TELEMETRY_DISABLED", "1")
    cognee.config.data_root_directory(str(project_root / ".cognee"))
    cognee.config.system_root_directory(str(project_root / ".cognee"))

    if all:
        return await _forget_all(dataset_name, hashes_path)

    return await _forget_targets(
        targets,  # type: ignore[arg-type]  # guarded above
        dataset_name=dataset_name,
        project_root=project_root,
        hashes_path=hashes_path,
    )


# ── internal ──


async def _forget_all(dataset_name: str, hashes_path: str) -> dict:
    """Delete the entire dataset and clear hashes.

    Regression: ``cognee.forget()``'s ``everything=True`` flag deletes
    *every* dataset the Cognee user owns and explicitly ignores the
    ``dataset``/``dataset_id`` arguments (verified against cognee==1.4.1's
    docstring and ``_forget_everything()`` implementation) — it is NOT
    "delete everything in this one dataset". Passing both together, as
    this used to do, silently wiped every other vault's knowledge graph
    sharing the same Cognee installation the first time a user ran
    ``forget --all`` in any one of them. The correct call for "delete
    this dataset, entirely" is ``dataset=dataset_name`` alone.
    """
    stored = load_hashes(hashes_path)
    count = len(stored)

    await cognee.forget(dataset=dataset_name)
    save_hashes(hashes_path, {})

    return {"forgotten": count, "dataset": dataset_name, "warnings": []}


async def _forget_targets(
    targets: list[str],
    *,
    dataset_name: str,
    project_root: Path,
    hashes_path: str,
) -> dict:
    """Forget specific files matched by *targets*."""
    stored = load_hashes(hashes_path)
    if not stored:
        return {"forgotten": 0, "dataset": dataset_name, "warnings": ["No indexed files found."]}

    indexed: dict[str, str] = {}  # relpath → data_id
    for rel, entry in stored.items():
        data_id = entry.get("data_id")
        if data_id:
            indexed[rel] = data_id

    forgotten_ids: set[str] = set()
    to_remove: set[str] = set()
    warnings: list[str] = []

    for target in targets:
        matched, reason = _match_target(target, indexed, project_root)

        if not matched:
            warnings.append(f"'{target}' not found in indexed files — skipped.")
            continue

        if reason == "basename" and len(matched) > 1:
            # Duplicate basenames from different directories.
            paths_str = "\n    ".join(sorted(matched))
            warnings.append(
                f"'{target}' matches multiple files, please specify a path:\n"
                f"    {paths_str}\n"
                f"  — skipped."
            )
            continue

        for rel in matched:
            data_id = indexed[rel]

            try:
                await cognee.forget(data_id=data_id, dataset=dataset_name)
            except Exception as e:
                warnings.append(f"Failed to forget '{rel}': {e}")
                continue

            to_remove.add(rel)
            forgotten_ids.add(data_id)

    # Update hashes.json
    new_hashes = {rel: entry for rel, entry in stored.items() if rel not in to_remove}
    save_hashes(hashes_path, new_hashes)

    return {
        "forgotten": len(to_remove),
        "dataset": dataset_name,
        "warnings": warnings,
    }


def _match_target(
    target: str,
    indexed: Mapping[str, str | None],
    project_root: Path,
) -> tuple[list[str], str]:
    """Match a single target against indexed paths.

    Returns:
        (matched_paths, reason) where reason is one of:
        ``"exact"``, ``"directory"``, ``"basename"``, ``"none"``.
    """
    # 1. Absolute path → relative
    p = Path(target)
    if p.is_absolute():
        try:
            target = str(p.relative_to(project_root))
        except ValueError:
            return [], "none"  # not under project root

    # 2. Exact match
    if target in indexed:
        return [target], "exact"

    # 3. Directory prefix match
    if not target.endswith("/"):
        dir_prefix = target + "/"
    else:
        dir_prefix = target
    dir_matches = [rel for rel in indexed if rel.startswith(dir_prefix)]
    if dir_matches:
        return dir_matches, "directory"

    # 4. Basename match (within directories)
    basename = Path(target).name
    basename_matches = [rel for rel in indexed if Path(rel).name == basename]
    if basename_matches:
        return basename_matches, "basename"

    return [], "none"
