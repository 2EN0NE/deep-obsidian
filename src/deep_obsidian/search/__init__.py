"""Search the knowledge graph with structured output and layer annotation."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from urllib.parse import unquote

import cognee
from cognee.modules.search.types import SearchType

from deep_obsidian.ingest._fingerprint import load_hashes
from deep_obsidian.ingest._health import clear_ladybug_lock
from deep_obsidian.settings import find_project_root, read_settings

# search() never routes to an LLM-completion SearchType (GRAPH_COMPLETION and
# friends) — it takes the union of pure vector-similarity and lexical/BM25
# chunk retrieval, both of which return raw text with no LLM call. LLM-
# synthesized answers are deep_obsidian.query.query()'s job, not this one's.
_NON_LLM_SEARCH_TYPES = (SearchType.CHUNKS, SearchType.CHUNKS_LEXICAL)
_MATCH_LABEL = {
    SearchType.CHUNKS: "vector",
    SearchType.CHUNKS_LEXICAL: "lexical",
}


def _has_cjk(s: str) -> bool:
    r"""Return True if *s* contains any CJK ideograph.

    Python's ``\w`` treats CJK characters as word characters, so the
    ASCII-oriented word-boundary regex in :func:`_word_boundary_match`
    has no boundary between two adjacent CJK words (e.g. no boundary
    between "习惯" and the surrounding characters in "如何养成习惯"),
    so it silently fails to match. CJK text has no whitespace between
    words in the first place, so a plain substring check is the correct
    fallback rather than trying to invent word boundaries.
    """
    return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in s)


def _word_boundary_match(tag: str, text: str) -> bool:
    r"""Return True if *tag* appears as a whole word in *text*.

    Uses negative lookbehind/ahead on word characters so ``habit``
    does not match ``inhabited``. For tags containing CJK characters
    (which have no word-boundary concept under Python's ``\w``), falls
    back to a plain case-insensitive substring match instead.
    """
    if not tag:
        return False
    if _has_cjk(tag):
        return tag.lower() in text.lower()
    return bool(re.search(r"(?<!\w)" + re.escape(tag) + r"(?!\w)", text, re.IGNORECASE))


def _build_source_index(project_root: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    """Build lookup indexes from hashes.json for resolving a chunk to its path.

    Primary: data_id -> vault-relative path. Cognee's chunk metadata
    exposes the ingested Data item's own id as ``document_id`` (surfaced
    here as ``metadata["data_id"]``), which equals the data_id we assign
    at ingest time in ``_build_data_item`` -- confirmed by direct
    comparison against hashes.json, so this is an exact, collision-free
    match, not a guess.

    Secondary: filename stem -> vault-relative path, used only as a
    fallback when a chunk's data_id isn't in hashes.json (a stale entry,
    a programmatic caller with no vault_path to load hashes.json from,
    etc). Cognee's chunk metadata only exposes ``document_name`` -- the
    file's stem, with no directory and no extension -- for this path, so
    it's best-effort: two files sharing a stem in different folders will
    collide and the first one (by hashes.json iteration order) wins.
    """
    if project_root is None:
        return {}, {}
    hashes_path = str(project_root / ".deep-obsidian" / "hashes.json")
    hashes = load_hashes(hashes_path)
    by_data_id: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    for rel_path, entry in hashes.items():
        data_id = entry.get("data_id") if isinstance(entry, dict) else None
        if data_id:
            by_data_id[str(data_id)] = rel_path
        by_stem.setdefault(Path(rel_path).stem, rel_path)
    return by_data_id, by_stem


def _resolve_source_file(
    data_id: str | None,
    document_name: str | None,
    by_data_id: dict[str, str],
    by_stem: dict[str, str],
) -> str:
    """Resolve a chunk back to its vault-relative path.

    Prefers an exact ``data_id`` match. Falls back to decoding
    ``document_name`` (the file's stem, no directory/extension) and
    looking it up by stem -- e.g. a programmatic caller that passed
    ``dataset=`` without a resolvable ``vault_path``, so there's no
    hashes.json to check the data_id against. Falls back further to
    the bare decoded stem itself when neither resolves.
    """
    if data_id and data_id in by_data_id:
        return by_data_id[data_id]
    if not document_name:
        return ""
    stem = unquote(document_name)
    return by_stem.get(stem, stem)


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
    """Search the knowledge graph without any LLM involvement.

    Returns the union of vector-similarity (``SearchType.CHUNKS``) and
    keyword/BM25 (``SearchType.CHUNKS_LEXICAL``) chunk matches, deduplicated
    by chunk id — each catches hits the other misses (paraphrases vs. exact
    terms). Neither retrieval path calls an LLM. ``top_k`` applies to each
    of the two searches independently, so the deduplicated result can have
    up to ``2 * top_k`` items. Use :func:`deep_obsidian.query.query` for an
    LLM-synthesized answer instead of raw chunks.

    Returns a list of dicts with: label, content, source_file, kind, layer,
    match_type ("vector" or "lexical" — which retrieval found this chunk).
    """
    # Resolve vault_path to find project settings.
    # If the caller already named a specific dataset (a lower-level
    # override for programmatic callers — the CLI no longer exposes
    # this; it only exposes --dir, which maps to vault_path), project
    # settings are optional.
    lookup = Path(vault_path) if vault_path else Path.cwd()
    project_root = find_project_root(lookup)
    if dataset is None:
        if project_root is None:
            raise RuntimeError(
                "No .deep-obsidian/ directory found. "
                "Run 'deep-obsidian init' first in the project root,"
                " or specify --dir to point at the vault."
            )
        _settings = read_settings(project_root)
        dataset = _settings["name"]

    # Point Cognee at this vault's own database.  When project_root is
    # unavailable (an explicit dataset override with no resolvable vault
    # path), fall back to Cognee's default location — the same default
    # ingest() writes to when config overrides are set to a vault-specific
    # path that may not exist yet (or may have been cleaned), since the
    # actual persistence layer (kuzu) lives under the venv site-packages
    # regardless.
    if project_root is not None:
        clear_ladybug_lock(str(project_root))
        cognee.config.data_root_directory(str(project_root / ".cognee"))
        cognee.config.system_root_directory(str(project_root / ".cognee"))

    datasets = [dataset] if dataset else None

    # Cognee's recall() runs a hidden per-query "session turn analysis" LLM
    # call by default (Cognee 1.x's auto_feedback feature, on regardless of
    # query_type) to extract durable session guidance and rate prior
    # context — a feature deep_obsidian never uses (no session_id is ever
    # passed). Left enabled, it silently reintroduces an LLM round-trip
    # into a function documented as LLM-free, adding ~15-20s per call.
    # setdefault() so an explicit user override still wins.
    os.environ.setdefault("AUTO_FEEDBACK", "false")

    # Cognee sends product telemetry (including a tracking ID derived
    # from the configured LLM API key) to its own servers on every
    # recall/remember/forget call, via a lazy module-level aiohttp
    # session that's never explicitly closed — hence the "Unclosed
    # client session" warning at process exit. deep_obsidian is a
    # local-first, single-user tool (see the ENABLE_BACKEND_ACCESS_
    # CONTROL/COGNEE_SKIP_CONNECTION_TEST precedent), so telemetry is
    # off by default here too; setdefault() still lets a user opt in.
    os.environ.setdefault("TELEMETRY_DISABLED", "1")

    result_sets = await asyncio.gather(
        *(
            cognee.recall(
                query_text=query,
                datasets=datasets,
                top_k=top_k,
                query_type=search_type,
                auto_route=False,
            )
            for search_type in _NON_LLM_SEARCH_TYPES
        )
    )

    # Union, deduplicated by chunk id (falls back to text when a result
    # has no id) — vector and lexical retrieval commonly surface the same
    # chunk for a strong match.
    seen: set[str] = set()
    merged = []
    for search_type, results in zip(_NON_LLM_SEARCH_TYPES, result_sets):
        for r in results:
            text = getattr(r, "text", "") or ""
            meta = getattr(r, "metadata", {}) or {}
            dedup_key = meta.get("chunk_id") if isinstance(meta, dict) else None
            dedup_key = dedup_key or text
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            merged.append((search_type, r))

    by_data_id, by_stem = _build_source_index(project_root)

    items = []
    for search_type, r in merged:
        text = getattr(r, "text", "") or ""
        kind = getattr(r, "kind", "") or ""
        meta = getattr(r, "metadata", {}) or {}
        data_id = meta.get("data_id") if isinstance(meta, dict) else None
        document_name = meta.get("document_name") if isinstance(meta, dict) else None
        source_file = _resolve_source_file(data_id, document_name, by_data_id, by_stem)

        # Post-filter: tag (word-boundary match to avoid false positives
        # like tag="habit" matching "inhabited"). Also checks structured
        # tags metadata when Cognee returns it from external_metadata.
        if tag and not _tag_matches(tag, text, r):
            continue

        # Post-filter: wikilinks
        if linked_from and f"[[{linked_from}" not in text:
            continue
        if linked_to and f"[[{linked_to}" not in text:
            continue

        # Post-filter: source file path
        if source and source not in source_file:
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

        items.append(
            {
                "label": Path(source_file).stem
                if source_file
                else (unquote(document_name) if document_name else ""),
                "content": text,
                "source_file": source_file,
                "kind": kind,
                "layer": "structural",
                "match_type": _MATCH_LABEL[search_type],
            }
        )

    return items
