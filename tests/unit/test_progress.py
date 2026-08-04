"""Tests for progress persistence."""

import json
import tempfile
from pathlib import Path

import pytest

from deep_obsidian.ingest._progress import (
    ProgressStore,
)


class TestFileProgress:
    def test_load_empty(self) -> None:
        """Loading non-existent progress file returns empty set."""
        store = ProgressStore("/nonexistent/progress.json")
        assert store.completed == set()

    def test_load_existing(self) -> None:
        """Load an existing progress file."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "progress.json"
            fpath.write_text(json.dumps(["Books/habit.md", "Daily/2024-01-01.md"]))

            store = ProgressStore(str(fpath))
            assert "Books/habit.md" in store.completed
            assert "Daily/2024-01-01.md" in store.completed
            assert len(store.completed) == 2

    def test_mark_done_and_persist(self) -> None:
        """Marking files as done writes to JSON immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "progress.json"
            store = ProgressStore(str(fpath))

            store.mark_done("Books/habit.md")
            store.mark_done("Daily/journal.md")

            # Reload from disk
            store2 = ProgressStore(str(fpath))
            assert "Books/habit.md" in store2.completed
            assert "Daily/journal.md" in store2.completed

    def test_is_completed(self) -> None:
        """is_completed returns True only for done files."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "progress.json"
            store = ProgressStore(str(fpath))

            assert not store.is_completed("Books/habit.md")
            store.mark_done("Books/habit.md")
            assert store.is_completed("Books/habit.md")

    def test_corrupt_progress_file(self) -> None:
        """Corrupt JSON is treated as empty (resilient restart)."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "progress.json"
            fpath.write_text("{broken json!!!")

            store = ProgressStore(str(fpath))
            assert store.completed == set()
            # Should still be able to write fresh
            store.mark_done("note.md")
            assert store.is_completed("note.md")

    def test_reset(self) -> None:
        """Reset clears all progress and deletes file."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "progress.json"
            store = ProgressStore(str(fpath))
            store.mark_done("note1.md")
            store.mark_done("note2.md")

            store.reset()
            assert store.completed == set()
            assert not Path(str(fpath)).exists()

    def test_stats(self) -> None:
        """stats() raises NotImplementedError (not yet implemented)."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "progress.json"
            store = ProgressStore(str(fpath))

            with pytest.raises(NotImplementedError, match="not yet implemented"):
                store.stats()
