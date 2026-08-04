"""Tests for incremental ingest (fingerprint-based skip)."""


class TestIncrementalIngest:
    def test_second_ingest_skips_unchanged(self, tmp_path, mock_llm):
        """第二次 ingest 跳过未变化的文件"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Original\n\nContent here.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["success"] == 1
        assert r1["skipped"] == 0

        # Second ingest — no changes
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["skipped"] == 1
        assert r2["success"] == 0

    def test_modified_file_re_ingested(self, tmp_path, mock_llm):
        """修改后的文件会被重新 ingest"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        note = tmp_path / "note.md"
        note.write_text("# Original\n\nOld content.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["success"] == 1

        # Modify the file
        note.write_text("# Modified\n\nNew content here.")

        # Second ingest — should re-ingest
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["success"] == 1
        assert r2["skipped"] == 0

    def test_full_flag_ignores_hashes(self, tmp_path, mock_llm):
        """--full 强制全量重建"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Test\n\nContent.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["success"] == 1

        # Second ingest with full=True — should re-ingest even though unchanged
        r2 = asyncio.run(ingest(str(tmp_path), full=True))
        assert r2["success"] == 1
        assert r2["skipped"] == 0
