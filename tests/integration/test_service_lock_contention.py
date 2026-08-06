"""service daemon behavior when it hits an ingest lock held by another
process (SPEC-003 / ADR-0009, ticket 04) — a warning, not a crash.
"""

from __future__ import annotations

import asyncio


class TestInitialScanLockContention:
    def test_run_service_logs_warning_and_continues_when_lock_held(
        self, tmp_path, capsys, monkeypatch, mock_llm
    ):
        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.service import run_service
        from deep_obsidian.settings import init_project

        # A file must exist so the initial scan has real work to do —
        # ingest()'s "nothing changed" fast path never touches the lock
        # at all, so an empty vault would never hit the conflict.
        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="svc-lock-test")

        async def fake_watch(vault, project_root, shutdown_event, on_file_event):
            # No file events — service should reach here and return
            # immediately (simulating instant shutdown) without ever
            # having crashed on the initial scan's lock conflict.
            return

        monkeypatch.setattr("deep_obsidian.service.watch", fake_watch)

        with acquire(tmp_path, dataset="svc-lock-test", total=1) as handle:
            handle.update(phase="cognify", current=1, total=1, current_file="")
            asyncio.run(run_service(tmp_path))  # must not raise

        captured = capsys.readouterr()
        assert "warning" in captured.err.lower()
        assert "svc-lock-test" in captured.err


class TestFileEventLockContention:
    def test_on_file_event_logs_warning_and_does_not_crash_loop(
        self, tmp_path, capsys, monkeypatch, mock_llm
    ):
        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.service import run_service
        from deep_obsidian.settings import init_project

        note = tmp_path / "a.md"
        note.write_text("# A")
        init_project(tmp_path, name="svc-event-lock-test")

        async def fake_watch(vault, project_root, shutdown_event, on_file_event):
            # Initial full scan (no lock contention) has already
            # completed by the time watch() is called. Modify the file
            # so the simulated file-change event has real work to do,
            # then hold the lock while it fires — on_file_event() must
            # swallow the conflict, not propagate it and kill the
            # watcher loop.
            note.write_text("# A modified")
            with acquire(project_root, dataset="svc-event-lock-test", total=1) as handle:
                handle.update(phase="adding", current=1, total=1, current_file="a.md")
                await on_file_event("a.md", "modified")  # must not raise

        monkeypatch.setattr("deep_obsidian.service.watch", fake_watch)

        asyncio.run(run_service(tmp_path))  # must not raise

        captured = capsys.readouterr()
        assert "warning" in captured.err.lower()
        assert "svc-event-lock-test" in captured.err
