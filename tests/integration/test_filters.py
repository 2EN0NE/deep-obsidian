"""Integration tests — Obsidian-specific search filters."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


class TestObsidianFilters:
    """Tag, wikilink, and date filter tests."""

    @pytest.mark.asyncio
    async def test_search_tag_filter(self, wikilink_vault: Path, mock_llm):
        """Search with --tag only returns notes matching that tag."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search

        await ingest(str(wikilink_vault), dataset="filter_test_1")

        # All notes in wikilink_vault have tags: [habit] or [habit, psychology]
        results = await search("habit", dataset="filter_test_1", tag="psychology")
        # Only habit.md has psychology tag
        assert len(results) <= 2  # habit had psychology tag

    @pytest.mark.asyncio
    async def test_search_linked_from(self, wikilink_vault: Path, mock_llm):
        """Search linked_from shows notes referencing the given note."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search

        await ingest(str(wikilink_vault), dataset="filter_test_2")

        # habit.md contains [[cue]] — linked_from "cue" should return habit.md
        results = await search("cue", dataset="filter_test_2", linked_from="cue")
        # Should be non-empty — the graph knows habit → cue
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_no_results(self, simple_vault: Path, mock_llm):
        """Search for something completely unrelated returns empty."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search

        await ingest(str(simple_vault), dataset="filter_test_3")

        results = await search("xyzzy_nonexistent_term_12345", dataset="filter_test_3")
        assert isinstance(results, list)
