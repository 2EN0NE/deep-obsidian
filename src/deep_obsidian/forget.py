"""Forget — delete a project's knowledge graph."""

from __future__ import annotations

from pathlib import Path

import cognee

from deep_obsidian.settings import find_project_root, read_settings


async def forget(
    dataset: str | None = None,
    *,
    vault_path: str | Path | None = None,
) -> dict:
    """Delete the current project's dataset and knowledge graph."""
    lookup = Path(vault_path) if vault_path else Path.cwd()
    project_root = find_project_root(lookup)
    if project_root is None:
        raise RuntimeError(
            "No .deep-obsidian/ directory found. "
            "Run 'deep-obsidian init' first in the project root."
        )
    _settings = read_settings(project_root)
    dataset = dataset or _settings["name"]

    await cognee.forget(dataset=dataset, everything=True)
    return {"dataset": dataset, "status": "forgotten"}
