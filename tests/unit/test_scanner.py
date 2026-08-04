"""Tests for vault file scanner."""

import tempfile
from pathlib import Path

import pytest

from deep_obsidian.ingest._scanner import scan_vault


class TestVaultScanner:
    def test_flat_vault(self) -> None:
        """Scan a flat directory with .md files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note1.md").write_text("# Note 1")
            (root / "note2.md").write_text("# Note 2")
            (root / "readme.txt").write_text("not markdown")
            (root / ".obsidian").mkdir()

            files = scan_vault(str(root))
            names = sorted(f.name for f in files)
            assert names == ["note1.md", "note2.md"]

    def test_nested_directories(self) -> None:
        """Recursively scan subdirectories."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "root.md").write_text("# Root")
            sub = root / "Books"
            sub.mkdir()
            (sub / "book1.md").write_text("# Book 1")
            deep = sub / "Learning"
            deep.mkdir()
            (deep / "how-to-study.md").write_text("# Study")

            files = scan_vault(str(root))
            names = sorted(f.name for f in files)
            assert names == ["book1.md", "how-to-study.md", "root.md"]

    def test_skip_dot_directories(self) -> None:
        """Skip .obsidian/, .trash/, .git/ etc."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "visible.md").write_text("# Visible")
            (root / ".obsidian").mkdir()
            (root / ".obsidian" / "config.md").write_text("# Should be skipped")
            (root / ".trash").mkdir()
            (root / ".trash" / "deleted.md").write_text("# Skipped")

            files = scan_vault(str(root))
            names = [f.name for f in files]
            assert names == ["visible.md"]

    def test_skip_attachments(self) -> None:
        """Skip attachments/ directories."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.md").write_text("# Note")
            (root / "attachments").mkdir()
            (root / "attachments" / "image.png").touch()

            files = scan_vault(str(root))
            assert len(files) == 1
            assert files[0].name == "note.md"

    def test_empty_vault(self) -> None:
        """Empty directory → empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            files = scan_vault(str(tmp))
            assert files == []

    def test_no_md_files(self) -> None:
        """Directory with no markdown files → empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.csv").write_text("a,b,c")
            (root / "script.py").write_text("print('hi')")
            files = scan_vault(str(root))
            assert files == []

    def test_relative_paths_preserved(self) -> None:
        """File paths are relative to vault root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Books" / "Learning").mkdir(parents=True)
            (root / "Books" / "Learning" / "study.md").write_text("# Study")
            (root / "Daily").mkdir()
            (root / "Daily" / "2024-01-01.md").write_text("# Journal")

            files = scan_vault(str(root))
            rel_paths = [str(f) for f in files]
            assert "Books/Learning/study.md" in rel_paths
            assert "Daily/2024-01-01.md" in rel_paths

    def test_non_existent_vault_raises(self) -> None:
        """Non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            scan_vault("/nonexistent/path/vault")

    def test_path_is_file_not_dir_raises(self) -> None:
        """Path pointing to a file raises NotADirectoryError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            afile = root / "note.md"
            afile.write_text("# Note")
            with pytest.raises(NotADirectoryError):
                scan_vault(str(afile))
