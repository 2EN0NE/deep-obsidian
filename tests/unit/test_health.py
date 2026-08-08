"""Unit tests — health checks."""

from __future__ import annotations

import tempfile
from pathlib import Path

from deep_obsidian.ingest._health import _find_lock_file, clear_ladybug_lock


class TestFindLockFile:
    def test_no_lock(self) -> None:
        """No .cognee directory → None."""
        with tempfile.TemporaryDirectory() as tmp:
            assert _find_lock_file(tmp) is None

    def test_no_databases_dir(self) -> None:
        """Has .cognee but no databases → None."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".cognee").mkdir()
            assert _find_lock_file(tmp) is None

    def test_lock_exists(self) -> None:
        """Lock file found when present."""
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".cognee" / "databases" / "cognee_graph_ladybug" / "LOCK"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("12345")
            found = _find_lock_file(tmp)
            assert found is not None
            assert found.name == "LOCK"


class TestClearLock:
    def test_clear_lock_no_lock(self) -> None:
        """No lock → returns False."""
        with tempfile.TemporaryDirectory() as tmp:
            assert clear_ladybug_lock(tmp) is False

    def test_clear_lock_stale_pid(self) -> None:
        """Lock with non-existent PID → cleared, returns True."""
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".cognee" / "databases" / "cognee_graph_ladybug" / "LOCK"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("99999")  # likely non-existent PID
            assert clear_ladybug_lock(tmp) is True
            assert not lock_path.exists()

    def test_clear_lock_active_process_leaves_untouched(self) -> None:
        """Lock owned by a different, alive process must NOT be cleared —
        the primary defence against concurrent graph writes.

        Regression: only the stale-pid and no-lock paths of
        clear_ladybug_lock() had tests. The 'active lock, leave it alone'
        path had zero coverage.

        Uses a real subprocess that sleeps briefly so os.kill(pid, 0)
        confirms the pid is genuinely alive at check time.
        """
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".cognee" / "databases" / "cognee_graph_ladybug" / "LOCK"
            lock_path.parent.mkdir(parents=True)

            # Spawn a short-lived subprocess whose PID we can use.
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
            try:
                lock_path.write_text(str(child.pid))
                # Lock is held by a living, different process → must stay.
                assert clear_ladybug_lock(tmp) is False
                assert lock_path.exists(), (
                    "active lock held by a living process must NOT be removed"
                )
            finally:
                child.kill()
                child.wait()
