"""Tests for the ``status`` command's ingest run-state classification."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from deep_obsidian.ingest._progress_state import acquire
from deep_obsidian.settings import init_project
from deep_obsidian.status import status


class TestStatus:
    def test_idle_when_no_progress_file(self, tmp_path):
        init_project(tmp_path, name="idle-test")
        result = asyncio.run(status(vault_path=tmp_path))
        assert result["status"] == "idle"

    def test_running_when_pid_alive(self, tmp_path):
        init_project(tmp_path, name="running-test")
        with acquire(tmp_path, dataset="running-test", total=10) as handle:
            handle.update(phase="adding", current=3, total=10, current_file="note.md")
            result = asyncio.run(status(vault_path=tmp_path))

            assert result["status"] == "running"
            assert result["phase"] == "adding"
            assert result["current"] == 3
            assert result["total"] == 10
            assert result["current_file"] == "note.md"
            assert result["dataset"] == "running-test"
            assert "started_at" in result

    def test_stale_when_pid_dead(self, tmp_path):
        """A progress file left behind by a process that no longer exists
        (crash, SIGKILL) must be reported as stale with its last known
        progress — not silently treated as idle or running.
        """
        init_project(tmp_path, name="stale-test")

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()

        progress_path = tmp_path / ".deep-obsidian" / "progress.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        import json

        progress_path.write_text(
            json.dumps(
                {
                    "pid": dead.pid,
                    "dataset": "stale-test",
                    "phase": "adding",
                    "current": 2,
                    "total": 5,
                    "current_file": "note2.md",
                    "started_at": 0,
                }
            )
        )

        result = asyncio.run(status(vault_path=tmp_path))

        assert result["status"] == "stale"
        assert result["phase"] == "adding"
        assert result["current"] == 2
        assert result["total"] == 5
        assert result["current_file"] == "note2.md"

    def test_raises_when_not_a_project(self, tmp_path):
        with pytest.raises(RuntimeError):
            asyncio.run(status(vault_path=tmp_path))
