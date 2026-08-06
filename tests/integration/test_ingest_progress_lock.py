"""Integration tests for the ingest()-core progress/lock wiring (SPEC-003 / ADR-0009)."""

from __future__ import annotations

import asyncio

import pytest


class TestProgressWiring:
    def test_on_progress_sees_prior_persisted_state(self, tmp_path, mock_llm):
        """During Phase 1, read_state() must reflect real, live progress —
        not just be a dead file written once at the end.

        Each on_progress(i+1, ...) callback fires immediately after the
        ingest loop's own handle.update() call for that same item, so by
        the time on_progress(current, ...) fires, read_state()'s
        ``current`` already equals that same ``current`` — same-iteration,
        not lagging behind.
        """
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._progress_state import read_state
        from deep_obsidian.settings import init_project

        for i in range(1, 4):
            (tmp_path / f"note{i}.md").write_text(f"# Note {i}\n\nContent {i}.")
        init_project(tmp_path, name="wiring-test")

        seen: list[dict | None] = []

        def on_progress(current: int, total: int, desc: str) -> None:
            seen.append(read_state(tmp_path))

        asyncio.run(ingest(str(tmp_path), on_progress=on_progress))

        assert len(seen) == 3
        for i, state in enumerate(seen, start=1):
            assert state is not None
            assert state["phase"] == "adding"
            assert state["current"] == i
            assert state["total"] == 3
            assert state["current_file"] == f"note{i}.md"

    def test_cognify_phase_is_recorded(self, tmp_path, mock_llm):
        """cognify() is an opaque batch call with no per-item progress —
        the lock can only mark that this phase started, not a percentage
        (ADR-0009). Observed via on_cognify_start, which fires right after
        the handle has been updated to phase="cognify".
        """
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._progress_state import read_state
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Note\n\nSome content.")
        init_project(tmp_path, name="cognify-phase-test")

        seen: dict | None = None

        def on_cognify_start() -> None:
            nonlocal seen
            seen = read_state(tmp_path)

        asyncio.run(ingest(str(tmp_path), on_cognify_start=on_cognify_start))

        assert seen is not None
        assert seen["phase"] == "cognify"

    def test_lock_released_after_successful_ingest(self, tmp_path, mock_llm):
        """No orphaned lock/progress file after a clean run."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._progress_state import read_state
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Note\n\nSome content.")
        init_project(tmp_path, name="release-test")

        asyncio.run(ingest(str(tmp_path)))

        assert read_state(tmp_path) is None

    def test_no_lock_taken_when_nothing_to_do(self, tmp_path, mock_llm):
        """The all-unchanged fast path must not touch the lock file at all."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._progress_state import read_state
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Note\n\nSome content.")
        init_project(tmp_path, name="no-op-test")

        asyncio.run(ingest(str(tmp_path)))  # first run: adds the file
        assert read_state(tmp_path) is None

        seen: list[dict | None] = []

        def on_progress(current: int, total: int, desc: str) -> None:
            seen.append(read_state(tmp_path))

        result = asyncio.run(ingest(str(tmp_path), on_progress=on_progress))

        assert result["unchanged"] == 1
        # on_progress does fire once (existing "(skipped)" notification from
        # file classification), but no lock is ever acquired for this
        # all-unchanged fast path, so read_state() is None throughout.
        assert seen == [None]
        assert read_state(tmp_path) is None


class TestGracefulInterruptStillReleasesLock:
    """Extends tests/integration/test_interrupt_resilience.py's scenario:
    a KeyboardInterrupt-style interrupt propagates out of ingest() (it's a
    BaseException, not caught by the per-file ``except Exception``), and
    Python's ``with`` statement runs ProgressHandle.__exit__ during that
    unwind — so the lock must NOT be left behind, even though the
    interrupt happened mid-loop.
    """

    class _SimulatedInterrupt(KeyboardInterrupt):
        pass

    def test_lock_is_released_on_simulated_interrupt(self, tmp_path, mock_llm):
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._progress_state import read_state
        from deep_obsidian.settings import init_project

        for i in range(1, 5):
            (tmp_path / f"note{i}.md").write_text(f"# Note {i}\n\nContent {i}.")
        init_project(tmp_path, name="interrupt-lock-test")

        def on_progress(current: int, total: int, desc: str) -> None:
            if current == 2:
                raise self._SimulatedInterrupt("simulated Ctrl+C at file 2/4")

        with pytest.raises(self._SimulatedInterrupt):
            asyncio.run(ingest(str(tmp_path), on_progress=on_progress))

        assert read_state(tmp_path) is None, (
            "a graceful (catchable) interrupt must still release the lock via "
            "ProgressHandle.__exit__, not leave an orphaned progress.json behind"
        )


class TestConcurrentIngestRaises:
    """ingest() lets IngestAlreadyRunningError propagate naturally when the
    lock is already held — presenting it usefully to the user is ticket
    03/04's job (CLI / service), not ingest()'s.
    """

    def test_ingest_raises_when_lock_already_held(self, tmp_path, mock_llm):
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._progress_state import IngestAlreadyRunningError, acquire
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Note\n\nSome content.")
        init_project(tmp_path, name="concurrent-test")

        with acquire(tmp_path, dataset="someone-elses-run", total=1):
            with pytest.raises(IngestAlreadyRunningError):
                asyncio.run(ingest(str(tmp_path)))
