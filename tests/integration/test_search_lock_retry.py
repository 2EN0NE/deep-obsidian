"""Tests for ADR-0008: Ladybug lock contention retry in search()."""

from __future__ import annotations

import asyncio


class TestSearchLadybugLockRetry:
    """search() retries cognee.recall with exponential backoff when the
    Ladybug graph database is temporarily locked by a concurrent write
    (service's cognify, another ingest, etc.).
    """

    def test_search_retries_on_lock_error_then_succeeds(self, tmp_path, mock_llm, monkeypatch):
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# Habits\n\nHabits are automatic.")
        init_project(tmp_path, name="lock-retry")

        asyncio.run(ingest(str(tmp_path)))

        call_count = 0

        async def fake_recall(query_text, datasets, top_k, query_type, auto_route):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError(
                    "IO exception: Could not set lock on file "
                    "/tmp/test.lbug (Lock is held by PID 99999)"
                )
            # Third call succeeds — return a mock result
            return [
                type(
                    "FakeResult",
                    (),
                    {
                        "text": "Habits are automatic behaviors.",
                        "kind": "chunk",
                        "metadata": {
                            "chunk_id": "c1",
                            "data_id": "fake-id",
                            "document_name": "a.md",
                        },
                    },
                )()
            ]

        monkeypatch.setattr("deep_obsidian.search.cognee.recall", fake_recall)

        results = asyncio.run(search("habits", vault_path=str(tmp_path)))

        assert call_count > 2  # at least one retry happened across search types
        assert len(results) > 0
        assert results[0]["content"] == "Habits are automatic behaviors."

    def test_search_friendly_error_when_all_retries_exhausted(
        self, tmp_path, mock_llm, monkeypatch
    ):
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="lock-exhaust")

        asyncio.run(ingest(str(tmp_path)))

        async def fake_recall(query_text, datasets, top_k, query_type, auto_route):
            raise OSError(
                "IO exception: Could not set lock on file "
                "/tmp/test.lbug (Lock is held by PID 99999)"
            )

        monkeypatch.setattr("deep_obsidian.search.cognee.recall", fake_recall)

        import pytest

        with pytest.raises(RuntimeError, match="knowledge graph is currently being"):
            asyncio.run(search("test", vault_path=str(tmp_path)))

    def test_non_lock_errors_are_not_retried(self, tmp_path, mock_llm, monkeypatch):
        """Only lock-related errors trigger retries; unrelated exceptions
        (e.g. config errors) propagate immediately.
        """
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="lock-nonlock")

        asyncio.run(ingest(str(tmp_path)))

        async def fake_recall(query_text, datasets, top_k, query_type, auto_route):
            raise ValueError("Unrelated config error")

        monkeypatch.setattr("deep_obsidian.search.cognee.recall", fake_recall)

        import pytest

        with pytest.raises(ValueError, match="Unrelated config error"):
            asyncio.run(search("test", vault_path=str(tmp_path)))
