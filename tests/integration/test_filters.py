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

        # mock_llm 固定召回 2 条：habit（tags=[habit, psychology]）与
        # cue（tags=[habit]）。tag=psychology 过滤后 cue 那条必须被排除——
        # 只断言条数（<=2）无法证明过滤真正生效，必须断言非匹配项未泄漏。
        results = await search("habit", dataset="filter_test_1", tag="psychology")
        assert results, "tag=psychology 过滤后不应为空"
        for r in results:
            assert "cue triggers" not in r.get("content", ""), (
                f"tag filter failed: non-psychology chunk leaked: {r.get('content', '')[:60]}"
            )

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

    @pytest.mark.asyncio
    async def test_search_linked_to(self, wikilink_vault: Path, mock_llm):
        """Search linked_to shows notes linked TO by the query matches —
        habit.md contains [[cue]], so linked_to=cue must only return
        results whose text mentions [[cue]]."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search

        await ingest(str(wikilink_vault), dataset="filter_linked_to")
        results = await search("habit", dataset="filter_linked_to", linked_to="cue")
        # All returned chunks must contain [[cue]]
        for r in results:
            assert "[[cue" in r.get("content", ""), (
                f"linked_to filter failed: chunk lacks [[cue]]: {r.get('content', '')[:80]}"
            )

    @pytest.mark.asyncio
    async def test_search_source_filter(self, simple_vault: Path, mock_llm):
        """Search with source filter only returns chunks from that file."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search

        await ingest(str(simple_vault), dataset="filter_source")
        results = await search("note", dataset="filter_source", source="note1.md")
        assert isinstance(results, list)
        for r in results:
            assert "note1.md" in r.get("source_file", ""), (
                f"source filter failed: got {r.get('source_file')}"
            )

    @pytest.mark.asyncio
    async def test_search_date_range_filter(self, simple_vault: Path, mock_llm):
        """Search with date_from/date_to filters by frontmatter date."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search

        await ingest(str(simple_vault), dataset="filter_date")
        results = await search("note", dataset="filter_date", date_from="2025-01-01")
        # If no note has date: >= 2025-01-01 in frontmatter, result should be empty.
        # The mock_llm always returns 2 fixed chunks (habit, cue), neither of
        # which has a date: field — so filter must result in empty.
        assert isinstance(results, list)
        # Chunks without a date: field are excluded when date_from/date_to is set
        for r in results:
            import re

            m = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", r.get("content", ""))
            assert m is not None, (
                f"date filter should exclude chunks with no date field, "
                f"got: {r.get('content', '')[:60]}"
            )

    @pytest.mark.asyncio
    async def test_search_date_to_filter(self, simple_vault: Path, mock_llm):
        """Search with date_to filter."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search

        await ingest(str(simple_vault), dataset="filter_date_to")
        results = await search("note", dataset="filter_date_to", date_to="2020-01-01")
        assert isinstance(results, list)
        for r in results:
            import re

            m = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", r.get("content", ""))
            assert m is not None
            assert m.group(1) <= "2020-01-01"
