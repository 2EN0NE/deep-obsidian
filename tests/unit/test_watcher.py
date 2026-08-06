"""Tests for file watcher — debounce, skip-dir, event dispatch."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from deep_obsidian.service._watcher import _is_skip_dir, _relative_path


class TestSkipDir:
    def test_dot_directories_skipped(self):
        assert _is_skip_dir(".obsidian/config.md")
        assert _is_skip_dir(".trash/deleted.md")
        assert _is_skip_dir(".git/index.md")
        assert _is_skip_dir("notes/.obsidian/template.md")

    def test_known_dirs_skipped(self):
        assert _is_skip_dir("attachments/img.png")
        assert _is_skip_dir("node_modules/pkg/readme.md")
        assert _is_skip_dir("__pycache__/mod.cpython.md")

    def test_normal_dirs_allowed(self):
        assert not _is_skip_dir("notes/daily.md")
        assert not _is_skip_dir("Books/philosophy.md")
        assert not _is_skip_dir("a.md")

    def test_root_level_dot_file_not_skip_dir(self):
        """Files starting with . at root level are not skipped by _is_skip_dir."""
        # _is_skip_dir checks parent dirs, not filenames
        assert not _is_skip_dir(".hidden.md")


class TestRelativePath:
    def test_inside_vault(self):
        vault = Path("/home/user/vault")
        assert _relative_path("/home/user/vault/notes/a.md", vault) == "notes/a.md"

    def test_outside_vault_returns_none(self):
        vault = Path("/home/user/vault")
        assert _relative_path("/etc/passwd", vault) is None

    def test_vault_root_file(self):
        vault = Path("/home/user/vault")
        assert _relative_path("/home/user/vault/index.md", vault) == "index.md"


class TestWatcherDebounce:
    """End-to-end debounce tests using mocked awatch."""

    @pytest.mark.asyncio
    async def test_rapid_saves_merged(self, tmp_path, mock_llm):
        """Multiple events for same file within cooldown are merged."""
        from deep_obsidian.service._watcher import watch
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="test-vault")
        (tmp_path / "note.md").write_text("# Hello\n\nContent.")

        events_received = []
        shutdown = asyncio.Event()

        async def on_event(rel, event_type):
            events_received.append((rel, event_type))

        # Generate fake watchfiles events
        async def fake_awatch(*args, **kwargs):
            # Simulate 5 rapid modify events
            for _ in range(5):
                yield {(2, str(tmp_path / "note.md"))}  # Change.modified = 2
            shutdown.set()
            return
            yield  # make it a generator

        with patch("deep_obsidian.service._watcher.awatch", new=fake_awatch):
            await watch(tmp_path, tmp_path, shutdown, on_event)

        # All 5 events should be debounced into at most 1 (the first)
        # The initial event causes a created/modified classification
        assert len(events_received) <= 1

    @pytest.mark.asyncio
    async def test_non_md_files_ignored(self, tmp_path, mock_llm):
        """Non-.md files are silently ignored."""
        from deep_obsidian.service._watcher import watch
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="test-vault")

        events_received = []
        shutdown = asyncio.Event()

        async def on_event(rel, event_type):
            events_received.append((rel, event_type))

        async def fake_awatch(*args, **kwargs):
            yield {(2, str(tmp_path / "image.png"))}
            shutdown.set()
            return
            yield

        with patch("deep_obsidian.service._watcher.awatch", new=fake_awatch):
            await watch(tmp_path, tmp_path, shutdown, on_event)

        assert len(events_received) == 0

    @pytest.mark.asyncio
    async def test_deleted_event_dispatched(self, tmp_path, mock_llm):
        """Deletion events are forwarded to on_event."""
        from deep_obsidian.service._watcher import watch
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="test-vault")
        (tmp_path / "old.md").write_text("# Old\n\nTo be deleted.")

        events_received = []
        shutdown = asyncio.Event()

        async def on_event(rel, event_type):
            events_received.append((rel, event_type))

        async def fake_awatch(*args, **kwargs):
            yield {(3, str(tmp_path / "old.md"))}  # Change.deleted = 3
            shutdown.set()
            return
            yield

        with patch("deep_obsidian.service._watcher.awatch", new=fake_awatch):
            await watch(tmp_path, tmp_path, shutdown, on_event)

        assert len(events_received) == 1
        assert events_received[0][1] == "deleted"


class TestWatcherPollFallback:
    """The 30s polling fallback (ADR-0004) must catch changes that the
    primary ``awatch`` event stream misses entirely — the scenario it
    exists for (macOS FSEvents delay / Linux inotify queue overflow).

    Regression: this is the only branch of ``watch()`` with zero test
    coverage. All existing debounce tests drive the ``awatch`` path and
    never let the polling loop's body actually execute.
    """

    @pytest.mark.asyncio
    async def test_poll_detects_file_awatch_never_reported(self, tmp_path, mock_llm):
        """A file present on disk but absent from hashes.json (i.e. never
        seen by any awatch event) must still be dispatched as "created",
        via the periodic full-vault scan rather than the primary stream.
        """
        import deep_obsidian.service._watcher as watcher_mod
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="poll-test")
        (tmp_path / "missed.md").write_text("# Missed\n\nawatch never reported this one.")

        events_received = []
        shutdown = asyncio.Event()

        async def on_event(rel, event_type):
            events_received.append((rel, event_type))

        async def fake_awatch(*args, **kwargs):
            # A primary event stream that never reports anything for this
            # file — the only way it gets picked up is the poll fallback.
            await shutdown.wait()
            return
            yield  # pragma: no cover - makes this an async generator

        real_wait_for = asyncio.wait_for
        calls = {"n": 0}

        async def fake_wait_for(aw, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                # Collapse the 30s poll interval so the first pass runs
                # immediately instead of after a real 30s wait. Close the
                # unused awaitable so it doesn't leak an "never awaited"
                # warning — asyncio.wait_for() normally takes ownership of it.
                aw.close()
                raise TimeoutError
            return await real_wait_for(aw, timeout)

        with (
            patch.object(watcher_mod, "awatch", new=fake_awatch),
            patch.object(watcher_mod.asyncio, "wait_for", new=fake_wait_for),
        ):
            task = asyncio.create_task(watcher_mod.watch(tmp_path, tmp_path, shutdown, on_event))
            # Give the poll loop's first (immediately-elapsed) pass a chance
            # to run before we ask everything to shut down.
            deadline = asyncio.get_running_loop().time() + 5
            while not events_received and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
            shutdown.set()
            await asyncio.wait_for(task, timeout=5)

        expected = ("missed.md", "created")
        assert expected in events_received
