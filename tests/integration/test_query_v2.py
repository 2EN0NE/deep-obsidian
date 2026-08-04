"""Integration tests for query (LLM-synthesized answers)."""

import pytest


class TestQueryRequiresInit:
    """query 在未初始化的目录上必须报错"""

    def test_query_without_init_raises(self, tmp_path):
        from deep_obsidian.query import query

        import asyncio

        with pytest.raises(RuntimeError, match="init"):
            asyncio.run(query("what is a habit?", vault_path=str(tmp_path)))

    def test_query_after_ingest_returns_dict(self, tmp_path, mock_llm):
        """init + ingest 后 query 返回 {answer, sources}（可能走 fallback）"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        (tmp_path / "science.md").write_text(
            "# Science\n\nF = ma. Newton's second law."
        )
        init_project(tmp_path, name="test-vault")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))
        result = asyncio.run(
            query("what is Newton's second law?", vault_path=str(tmp_path))
        )

        assert isinstance(result, dict)
        assert "answer" in result
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0
        assert "sources" in result
        assert isinstance(result["sources"], list)

    def test_query_empty_vault_returns_answer(self, tmp_path):
        """空 vault 的 query 不崩溃"""
        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="empty-vault")

        import asyncio

        result = asyncio.run(query("anything", vault_path=str(tmp_path)))
        assert "answer" in result
        assert "sources" in result
        assert len(result["answer"]) > 0
