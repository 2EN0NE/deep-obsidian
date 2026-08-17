"""Tests for cross-process ingest progress state + single-instance lock."""

from __future__ import annotations

import json
import os

import pytest

from deep_obsidian.ingest._progress_state import (
    IngestAlreadyRunningError,
    acquire,
    read_state,
)


class TestReadState:
    def test_missing_file_returns_none(self, tmp_path):
        assert read_state(tmp_path) is None


class TestAcquire:
    def test_acquire_writes_readable_initial_state(self, tmp_path):
        with acquire(tmp_path, dataset="my-vault", total=42) as handle:
            state = read_state(tmp_path)
            assert state is not None
            assert state["pid"] == os.getpid()
            assert state["dataset"] == "my-vault"
            assert state["total"] == 42
            assert state["current"] == 0
            assert state["current_file"] == ""
            assert "started_at" in state
            assert "phase" in state
            assert handle is not None

    def test_acquire_while_alive_lock_held_raises(self, tmp_path):
        with acquire(tmp_path, dataset="my-vault", total=42):
            with pytest.raises(IngestAlreadyRunningError) as excinfo:
                acquire(tmp_path, dataset="my-vault", total=1)
            assert excinfo.value.state["dataset"] == "my-vault"
            assert excinfo.value.state["pid"] == os.getpid()

    def test_acquire_cleans_up_orphaned_lock_from_dead_pid(self, tmp_path):
        """A lock file left behind by a process that no longer exists
        (crash, SIGKILL) must not permanently block new ingests.
        """
        progress_path = tmp_path / ".deep-obsidian" / "progress.json"
        progress_path.parent.mkdir(parents=True)
        progress_path.write_text(
            json.dumps({"pid": 99999, "dataset": "old-run", "phase": "cognify", "total": 10})
        )

        with acquire(tmp_path, dataset="my-vault", total=42) as handle:
            assert handle is not None
            state = read_state(tmp_path)
            assert state is not None
            assert state["dataset"] == "my-vault"
            assert state["pid"] == os.getpid()


class TestUpdate:
    def test_update_writes_readable_state(self, tmp_path):
        with acquire(tmp_path, dataset="my-vault", total=10) as handle:
            handle.update(phase="adding", current=3, total=10, current_file="note.md")
            state = read_state(tmp_path)
            assert state is not None
            assert state["phase"] == "adding"
            assert state["current"] == 3
            assert state["total"] == 10
            assert state["current_file"] == "note.md"


class TestRelease:
    def test_normal_exit_removes_state_file(self, tmp_path):
        with acquire(tmp_path, dataset="my-vault", total=10):
            pass
        assert read_state(tmp_path) is None

    def test_exception_exit_still_removes_state_file(self, tmp_path):
        with pytest.raises(ValueError, match="boom"):
            with acquire(tmp_path, dataset="my-vault", total=10):
                raise ValueError("boom")
        assert read_state(tmp_path) is None

    def test_can_reacquire_after_release(self, tmp_path):
        with acquire(tmp_path, dataset="my-vault", total=10):
            pass
        with acquire(tmp_path, dataset="another-vault", total=5) as handle:
            assert handle is not None
            state = read_state(tmp_path)
            assert state is not None
            assert state["dataset"] == "another-vault"


class TestUserLevelVaultIsolation:
    """用户级配置下进度/锁文件按 vault 隔离（ADR-0014）——
    两个独立 vault 不共享 ~/.deep-obsidian/progress.json，避免假互斥。
    """

    def test_user_level_progress_scoped_under_vault_hash(self, tmp_path):
        from deep_obsidian.settings import vault_path_hash

        config_dir = tmp_path / ".deep-obsidian"
        vault = tmp_path / "vault"
        with acquire(config_dir, dataset="v", total=1, vault=vault) as handle:
            assert handle is not None
            expected = config_dir / "vaults" / vault_path_hash(vault) / "progress.json"
            assert expected.is_file()
            # 平铺位置不得出现
            assert not (config_dir / "progress.json").exists()
            assert read_state(config_dir, vault=vault) is not None
            # 不带 vault 读不到（不同路径）
            assert read_state(config_dir) is None

    def test_two_vaults_do_not_conflict_at_user_level(self, tmp_path):
        config_dir = tmp_path / ".deep-obsidian"
        vault_a = tmp_path / "vaultA"
        vault_b = tmp_path / "vaultB"
        with acquire(config_dir, dataset="A", total=1, vault=vault_a):
            # vault B 的锁不受 vault A 影响
            with acquire(config_dir, dataset="B", total=1, vault=vault_b) as handle:
                assert handle is not None
                state_b = read_state(config_dir, vault=vault_b)
                assert state_b is not None
                assert state_b["dataset"] == "B"

    def test_project_level_keeps_flat_location(self, tmp_path):
        """项目级（单 vault）仍使用 config_dir/progress.json。"""
        with acquire(tmp_path, dataset="p", total=1) as handle:
            assert handle is not None
            assert (tmp_path / "progress.json").is_file()


class TestUpdateCrashSafety:
    """Regression coverage mirroring ADR-0005's guarantee for
    hashes.json: a process kill mid-write must never leave the
    progress state file truncated or corrupted.
    """

    def test_crash_during_replace_preserves_old_content(self, tmp_path, monkeypatch):
        with acquire(tmp_path, dataset="my-vault", total=10) as handle:
            handle.update(phase="adding", current=1, total=10, current_file="a.md")
            original = read_state(tmp_path)

            real_replace = os.replace

            def _boom_replace(src, dst):
                raise OSError("simulated crash during os.replace")

            monkeypatch.setattr(os, "replace", _boom_replace)
            try:
                with pytest.raises(OSError, match="simulated crash"):
                    handle.update(phase="adding", current=2, total=10, current_file="b.md")
            finally:
                monkeypatch.setattr(os, "replace", real_replace)

            assert read_state(tmp_path) == original
            # acquire() 的 config_dir 语义：progress.json 直接在 config_dir 下
            leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
            assert leftovers == [], f"temp file(s) not cleaned up: {leftovers}"
