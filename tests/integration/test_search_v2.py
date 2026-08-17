"""Integration tests for search with settings-based project lookup."""

import pytest


class TestSearchRequiresInit:
    """search 在未初始化的目录上必须报错"""

    def test_search_without_init_raises(self, tmp_path, monkeypatch):
        """无任何配置（无项目级也无用户级基础层）时 search 应报错
        （ADR-0014：用户级是必需基础层）。"""
        import asyncio

        from deep_obsidian.search import search

        monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
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


class TestSearchDedup:
    """search() 合并两路检索结果（向量 + 词汇）时按 chunk_id 去重。

    Regression: mock_llm 的 _fake_recall 返回的结果 chunk_id 均为 None，
    走 text fallback 去重路径；真实 Cognee 返回的 chunk 有 chunk_id，
    但从未被测试覆盖。
    """

    def test_dedup_by_chunk_id_collapses_duplicates(self, tmp_path, mock_llm, monkeypatch):
        """两条结果有相同 chunk_id → 去重后只剩一条。"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# Habits\n\nAutomatic behaviors.")
        init_project(tmp_path, name="dedup-chunk-id")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))

        # Patch _recall_with_retry so BOTH search types return the same chunk
        # (same chunk_id) — vector and lexical both find the same passage.
        async def _fake_same_chunk(*args, **kwargs):
            return [
                type(
                    "R",
                    (),
                    {
                        "text": "Habits are automatic behaviors.",
                        "kind": "chunk",
                        "metadata": {
                            "chunk_id": "shared-chunk-001",
                            "data_id": "id-1",
                            "document_name": "a.md",
                        },
                    },
                )()
            ]

        monkeypatch.setattr("deep_obsidian.search._recall_with_retry", _fake_same_chunk)

        results = asyncio.run(search("habits", vault_path=str(tmp_path)))
        assert len(results) == 1, (
            f"chunks with same chunk_id must be deduplicated to 1, got {len(results)}"
        )

    def test_dedup_by_chunk_id_keeps_different_chunks(self, tmp_path, mock_llm, monkeypatch):
        """两条结果有不同 chunk_id → 保留两条。"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# Habits\n\nContent.")
        init_project(tmp_path, name="dedup-diff-id")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))

        async def _fake_two_chunks(*args, **kwargs):
            return [
                type(
                    "R",
                    (),
                    {
                        "text": "Habits are automatic.",
                        "kind": "chunk",
                        "metadata": {"chunk_id": "c1", "data_id": "id-1", "document_name": "a.md"},
                    },
                )(),
                type(
                    "R",
                    (),
                    {
                        "text": "A cue triggers the loop.",
                        "kind": "chunk",
                        "metadata": {"chunk_id": "c2", "data_id": "id-2", "document_name": "a.md"},
                    },
                )(),
            ]

        monkeypatch.setattr("deep_obsidian.search._recall_with_retry", _fake_two_chunks)

        results = asyncio.run(search("habits", vault_path=str(tmp_path)))
        assert len(results) == 2, (
            f"chunks with different chunk_id must both be kept, got {len(results)}"
        )
