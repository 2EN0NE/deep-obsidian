"""Integration tests: forget() refuses to operate while an ingest holds
the project lock (SPEC-003 single-instance lock guarding both write
paths — ingest and forget — against concurrent mutation of the same
Cognee graph database and hashes.json).
"""

from __future__ import annotations

import asyncio


class TestForgetLockContention:
    def test_forget_raises_when_ingest_lock_held(self, tmp_path, mock_llm):
        """forget() must refuse to run when an ingest is actively holding
        the progress lock, rather than racing on the Cognee graph database
        and producing a raw Ladybug IOException or corrupted hashes.json.
        """
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="forget-lock-test")

        # Seed the vault so forget has something to operate on.
        asyncio.run(ingest(str(tmp_path)))

        import pytest

        with acquire(tmp_path / ".deep-obsidian", dataset="forget-lock-test", total=1) as handle:
            handle.update(phase="cognify", current=1, total=1, current_file="")
            with pytest.raises(RuntimeError, match="Cannot forget while an ingest is running"):
                asyncio.run(forget(["a.md"], vault_path=str(tmp_path)))

    def test_forget_proceeds_normally_when_no_ingest_running(self, tmp_path, mock_llm):
        """Sanity: forget() works as before when no ingest holds the lock."""
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="forget-normal-test")

        asyncio.run(ingest(str(tmp_path)))

        result = asyncio.run(forget(["a.md"], vault_path=str(tmp_path)))
        assert result["forgotten"] == 1
        assert result["warnings"] == []

    def test_forget_proceeds_when_lock_file_is_stale_dead_pid(
        self, tmp_path, mock_llm, monkeypatch
    ):
        """A progress.json left by a dead process must NOT block forget —
        only a genuinely alive ingest should be treated as a conflict.
        """
        import json

        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="forget-stale-test")

        asyncio.run(ingest(str(tmp_path)))

        # Write a stale lock with a dead PID.
        progress_path = tmp_path / ".deep-obsidian" / "progress.json"
        progress_path.write_text(
            json.dumps(
                {
                    "pid": 99999,
                    "dataset": "forget-stale-test",
                    "phase": "cognify",
                    "current": 5,
                    "total": 10,
                }
            )
        )

        # is_process_alive returns False for pid 99999 by default (os.kill
        # raises OSError for non-existent pids), so forget should proceed.
        result = asyncio.run(forget(["a.md"], vault_path=str(tmp_path)))
        assert result["forgotten"] == 1
