"""Search the knowledge graph with structured output and layer annotation."""

from __future__ import annotations

import re
from pathlib import Path

import cognee

from deep_obsidian.settings import find_project_root, read_settings


def _word_boundary_match(tag: str, text: str) -> bool:
    """Return True if *tag* appears as a whole word in *text*.

    Uses negative lookbehind/ahead on word characters so ``habit``
    does not match ``inhabited``.
    """
    return bool(re.search(r"(?<!\w)" + re.escape(tag) + r"(?!\w)", text, re.IGNORECASE))


def _tag_matches(tag: str, text: str, result: object) -> bool:
    """Return True if *tag* is found in the result's text OR structured metadata.

    Checks both the free-text content (word-boundary match) and any structured
    tags list Cognee may have preserved from ``external_metadata`` during ingest.
    This handles notes whose tags exist only in YAML frontmatter and may not
    appear in the recalled text snippet.
    """
    # 1) Check structured tags metadata first
    structured_tags = getattr(result, "tags", None)
    if structured_tags is None:
        meta = getattr(result, "metadata", {}) or {}
        if isinstance(meta, dict):
            structured_tags = meta.get("tags", [])
    if isinstance(structured_tags, (list, tuple)) and tag in structured_tags:
        return True

    # 2) Fall back to word-boundary text search
    return _word_boundary_match(tag, text)


async def search(
    query: str,
    *,
    dataset: str | None = None,
    vault_path: str | Path | None = None,
    top_k: int = 5,
    tag: str | None = None,
    linked_to: str | None = None,
    linked_from: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source: str | None = None,
) -> list[dict]:
    """Search the knowledge graph with optional Obsidian filters.

    Returns a list of dicts with: label, content, source_file, kind, layer.
    """
    # Resolve vault_path to find project settings
    lookup = Path(vault_path) if vault_path else Path.cwd()
    project_root = find_project_root(lookup)
    if project_root is None:
        raise RuntimeError(
            "No .deep-obsidian/ directory found. "
            "Run 'deep-obsidian init' first in the project root."
        )
    _settings = read_settings(project_root)
    dataset = dataset or _settings["name"]

    datasets = [dataset] if dataset else None

    results = await cognee.recall(
        query_text=query,
        datasets=datasets,
        top_k=top_k,
        only_context=True,
    )

    items = []
    for r in results:
        text = getattr(r, "text", "") or ""
        kind = getattr(r, "kind", "") or ""
        src = getattr(r, "source", "") or ""

        # Post-filter: tag (word-boundary match to avoid false positives
        # like tag="habit" matching "inhabited"). Also checks structured
        # tags metadata when Cognee returns it from external_metadata.
        if tag:
            if not _tag_matches(tag, text, r):
                continue

        # Post-filter: wikilinks
        if linked_from and f"[[{linked_from}" not in text:
            continue
        if linked_to and f"[[{linked_to}" not in text:
            continue

        # Post-filter: date range
        if date_from or date_to:
            m = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", text)
            if not m:
                continue
            d = m.group(1)
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue

        # Determine layer
        layer = "semantic"
        if "Node:" not in text and len(text) < 500:
            # Short text without graph structure is likely a raw chunk or metadata
            layer = "structural"

        items.append(
            {
                "label": getattr(r, "label", ""),
                "content": text,
                "source_file": src or str(getattr(r, "file_path", "")),
                "kind": kind,
                "layer": layer,
            }
        )

    return items
