"""Integration tests for search with settings-based project lookup."""

import pytest


class TestSearchRequiresInit:
    """search 在未初始化的目录上必须报错"""

    def test_search_without_init_raises(self, tmp_path):
        """未 init 的目录执行 search 应报错"""
        import asyncio

        from deep_obsidian.search import search

        with pytest.raises(RuntimeError, match="init"):
            asyncio.run(search("test query", vault_path=str(tmp_path)))

    def test_search_after_ingest_returns_results(self, tmp_path, mock_llm):
        """init + ingest 后 search 返回结果"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text(
            "# Habits\n\nHabits are automatic behaviors triggered by cues."
        )
        init_project(tmp_path, name="test-vault")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))
        results = asyncio.run(search("habits", vault_path=str(tmp_path)))

        assert isinstance(results, list)
        assert len(results) > 0
        assert "content" in results[0]
        assert "source_file" in results[0]


class TestSearchFields:
    """search 返回的结构化字段"""

    def test_result_has_required_fields(self, tmp_path, mock_llm):
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "post.md").write_text("# Test\n\nSome unique content here.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))
        results = asyncio.run(search("unique content", vault_path=str(tmp_path)))

        assert len(results) > 0
        r = results[0]
        assert "content" in r
        assert "source_file" in r
        assert "kind" in r
        assert "layer" in r
