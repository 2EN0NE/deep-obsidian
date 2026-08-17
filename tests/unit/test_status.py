"""Tests for the ``status`` command's ingest run-state classification."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from deep_obsidian.ingest._progress_state import acquire
from deep_obsidian.settings import init_project
from deep_obsidian.status import status


@pytest.fixture
def user_level(tmp_path, monkeypatch):
    """Create the user-level base config (ADR-0014 required layer)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    init_project(home, name="user", level="user")
    return home


def _config_dir(root):
    from pathlib import Path

    return Path(root) / ".deep-obsidian"


class TestStatus:
    def test_idle_when_no_progress_file(self, tmp_path, user_level):
        init_project(tmp_path, name="idle-test")
        result = asyncio.run(status(vault_path=tmp_path))
        assert result["status"] == "idle"

    def test_running_when_pid_alive(self, tmp_path, user_level):
        init_project(tmp_path, name="running-test")
        with acquire(_config_dir(tmp_path), dataset="running-test", total=10) as handle:
            handle.update(phase="adding", current=3, total=10, current_file="note.md")
            result = asyncio.run(status(vault_path=tmp_path))

            assert result["status"] == "running"
            assert result["phase"] == "adding"
            assert result["current"] == 3
            assert result["total"] == 10
            assert result["current_file"] == "note.md"
            assert result["dataset"] == "running-test"
            assert "started_at" in result

    def test_stale_when_pid_dead(self, tmp_path, user_level):
        """A progress file left behind by a process that no longer exists
        (crash, SIGKILL) must be reported as stale with its last known
        progress — not silently treated as idle or running.
        """
        init_project(tmp_path, name="stale-test")

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()

        progress_path = _config_dir(tmp_path) / "progress.json"
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

    def test_raises_without_any_config(self, tmp_path, monkeypatch):
        """无用户级也无项目级配置时，status 报清晰错误（ADR-0014 用户级必需）。"""
        home = tmp_path / "nohome"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        with pytest.raises(RuntimeError, match="用户级配置缺失"):
            asyncio.run(status(vault_path=tmp_path))
