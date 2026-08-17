"""Integration tests for ingest with settings-based project lookup."""

import pytest


class TestIngestRequiresInit:
    """ingest 在未初始化的目录上必须报错"""

    def test_ingest_without_init_raises(self, tmp_path, monkeypatch):
        """无任何配置（无项目级也无用户级基础层）时 ingest 应报错
        （ADR-0014：用户级是必需基础层）。"""
        from deep_obsidian.ingest import ingest

        monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
        (tmp_path / "test.md").write_text("# Hello\n\nSome content.")
        with pytest.raises(RuntimeError, match="init"):
            import asyncio

            asyncio.run(ingest(str(tmp_path)))

    def test_ingest_after_init_works(self, tmp_path, mock_llm):
        """init 后 ingest 正常执行"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "test.md").write_text("# Hello\n\nSome content here.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        result = asyncio.run(ingest(str(tmp_path)))
        assert result["total"] >= 1
        assert result["added"] >= 1
        assert result["failed"] == 0

    def test_ingest_single_file(self, tmp_path, mock_llm):
        """ingest 支持单文件 target"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "posts").mkdir()
        (tmp_path / "posts" / "a.md").write_text("# Post A\n\nContent A.")
        (tmp_path / "posts" / "b.md").write_text("# Post B\n\nContent B.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        result = asyncio.run(ingest(str(tmp_path / "posts" / "a.md")))
        assert result["total"] == 1
        assert result["added"] == 1

    def test_ingest_subdirectory(self, tmp_path, mock_llm):
        """ingest 支持子目录 target"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.md").write_text("# A\n\nContent.")
        (sub / "b.md").write_text("# B\n\nContent.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        result = asyncio.run(ingest(str(sub)))
        assert result["total"] == 2
        assert result["added"] == 2
