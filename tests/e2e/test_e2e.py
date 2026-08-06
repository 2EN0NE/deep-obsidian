"""E2E tests — full pipeline from vault changes to search results."""

from __future__ import annotations

import asyncio
import json


class TestFullIngestPipeline:
    """E2E: ingest → search, covering add/modify/delete flows."""

    def test_ingest_new_file_searchable(self, tmp_path, mock_llm):
        """New file appears in search after ingest."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.search import search
        from deep_obsidian.settings import init_project

        (tmp_path / "journal.md").write_text(
            "# Daily Journal\n\nToday I learned about second-order thinking."
        )
        init_project(tmp_path, name="e2e-vault")

        r = asyncio.run(ingest(str(tmp_path)))
        assert r["added"] == 1
        assert r["failed"] == 0

        results = asyncio.run(search("second-order thinking", vault_path=str(tmp_path)))
        assert len(results) > 0

    def test_modified_file_updates_graph(self, tmp_path, mock_llm):
        """Modifying a file and re-ingesting updates the graph."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        note = tmp_path / "note.md"
        note.write_text("# Note\n\nOriginal content about habits.")
        init_project(tmp_path, name="e2e-vault")

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 1

        # Modify
        note.write_text("# Note\n\nUpdated content about meditation.")
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["modified"] == 1

    def test_deleted_file_cleaned_up(self, tmp_path, mock_llm):
        """Deleting a file and re-ingesting reports deletion and actually
        forgets it from Cognee (no warnings) — not just a count that stays
        1 regardless of whether the underlying cognee.forget() call
        actually succeeded.
        """
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        note = tmp_path / "temp.md"
        note.write_text("# Temporary\n\nWill be deleted.")
        init_project(tmp_path, name="e2e-vault")

        # Ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 1

        # Delete and re-ingest
        note.unlink()
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["deleted"] == 1
        # A failed cognee.forget() call is caught and demoted to a
        # warning rather than raised (see _forget_one's caller) — so
        # "deleted == 1" alone does NOT prove the file was actually
        # forgotten from Cognee. Assert no warnings too, otherwise a
        # broken forget() call (e.g. wrong kwarg name) silently passes.
        assert r2.get("warnings", []) == []

    def test_incremental_stats_accurate(self, tmp_path, mock_llm):
        """Mixed add/modify/delete/unchanged in a single run."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "keep.md").write_text("# Keep\n\nStays the same.")
        (tmp_path / "change.md").write_text("# Change\n\nWill be modified.")
        init_project(tmp_path, name="e2e-vault")

        # Initial ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 2

        # Delete one, add one
        (tmp_path / "change.md").unlink()
        (tmp_path / "new.md").write_text("# New\n\nBrand new file.")

        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["added"] == 1  # new.md
        assert r2["deleted"] == 1  # change.md was deleted
        assert r2["unchanged"] == 1  # keep.md
        assert r2.get("warnings", []) == []

    def test_hashes_persisted(self, tmp_path, mock_llm):
        """After ingest, hashes.json contains hash and data_id."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Test\n\nContent.")
        init_project(tmp_path, name="e2e-vault")

        asyncio.run(ingest(str(tmp_path)))

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "note.md" in hashes
        assert "hash" in hashes["note.md"]
        assert "data_id" in hashes["note.md"]

    def test_empty_vault_no_error(self, tmp_path, mock_llm):
        """Ingesting an empty vault returns zero counts, no errors."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="empty")

        r = asyncio.run(ingest(str(tmp_path)))
        assert r["total"] == 0
        assert r["failed"] == 0

    def test_llm_degraded_preserves_structural_data(self, tmp_path, mock_llm_degraded):
        """LLM unavailable → warning recorded, file still counted, hashes persisted."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Note\n\nContent.")
        init_project(tmp_path, name="degraded-vault")

        r = asyncio.run(ingest(str(tmp_path)))
        assert r["added"] == 1
        assert r["failed"] == 0
        assert len(r["warnings"]) == 1
        assert "LLM" in r["warnings"][0]

        # Hash persisted even though LLM degraded
        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "note.md" in hashes

        # Second run skips unchanged file despite no data_id
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["unchanged"] == 1


class TestIncrementalSkip:
    """E2E: incremental skip prevents unnecessary Cognee initialization."""

    def test_second_ingest_skips_all_unchanged(self, tmp_path, mock_llm):
        """Second ingest with no changes returns immediately, zero Cognee init."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A\n\nContent A.")
        (tmp_path / "b.md").write_text("# B\n\nContent B.")
        init_project(tmp_path, name="skip-test")

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 2

        # Verify hashes are populated
        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert len(hashes) == 2
        assert "a.md" in hashes
        assert "hash" in hashes["a.md"]

        # Second ingest — all files unchanged, should skip without Cognee init
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["unchanged"] == 2
        assert r2["added"] == 0
        assert r2["modified"] == 0
        assert r2["total"] == 0

    def test_hashes_saved_before_cognify_interrupt(self, tmp_path, mock_llm, monkeypatch):
        """Hashes are persisted before cognify so interrupt doesn't lose state.

        When cognify is interrupted (Ctrl+C), hashes should already be
        saved from Phase 1.  The next ingest should skip all files.
        """
        from unittest.mock import patch

        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Note\n\nImportant content.")
        init_project(tmp_path, name="interrupt-test")

        # Replace cognify with one that raises to simulate interrupt
        async def _fake_cognify_crash(**kwargs):
            raise RuntimeError("Simulated cognify crash")

        with (
            patch("cognee.cognify", new=_fake_cognify_crash),
            patch("cognee.api.v1.cognify.cognify", new=_fake_cognify_crash),
        ):
            r1 = asyncio.run(ingest(str(tmp_path)))
            # ingest should still report the file as added (Phase 1 succeeded)
            assert r1["added"] == 1
            # cognify failure recorded as warning
            assert len(r1["warnings"]) == 1
            assert "Cognify failed" in r1["warnings"][0]

        # Verify hashes were saved despite cognify crash
        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "note.md" in hashes
        assert "hash" in hashes["note.md"]

        # Second ingest — should skip unchanged file, no Cognee init needed
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["unchanged"] == 1
        assert r2["added"] == 0
        assert r2["total"] == 0

    def test_skip_with_mixed_changes(self, tmp_path, mock_llm):
        """Only changed files are processed; unchanged files skipped."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "keep.md").write_text("# Keep\n\nSame.")
        (tmp_path / "change.md").write_text("# V1\n\nOriginal.")
        init_project(tmp_path, name="mixed-test")

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 2

        # Modify one file
        (tmp_path / "change.md").write_text("# V2\n\nModified.")

        # Second ingest
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["modified"] == 1
        assert r2["unchanged"] == 1
        assert r2["total"] == 1  # 1 modified + 0 deleted


class TestServiceLifecycle:
    """E2E: service start/stop/status and PID management."""

    def test_status_stopped_by_default(self, tmp_path):
        """Service status is 'stopped' when no service is running."""
        from deep_obsidian.service import service_status
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="svc-test")
        st = service_status(tmp_path)
        assert st["status"] == "stopped"

    def test_pid_write_and_cleanup(self, tmp_path):
        """PID file is written and can be cleared."""
        from deep_obsidian.service._pidfile import (
            is_process_alive,
            read_pid,
            remove_pid,
            write_pid,
        )
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="svc-test")
        write_pid(tmp_path, 99999)
        assert read_pid(tmp_path) == 99999
        assert not is_process_alive(99999)

        remove_pid(tmp_path)
        assert read_pid(tmp_path) is None

    def test_stale_pid_detected(self, tmp_path, monkeypatch):
        """Stale PID file is reported correctly — uses mocked os.kill."""
        from deep_obsidian.service import service_status
        from deep_obsidian.service._pidfile import write_pid
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="svc-test")
        write_pid(tmp_path, 99999)

        # Mock os.kill to return False for PID 99999 (process doesn't exist)
        monkeypatch.setattr("os.kill", lambda pid, sig: (_ for _ in ()).throw(OSError()))
        st = service_status(tmp_path)
        assert st["status"] == "stale_pid"
        assert st["pid"] == 99999


class TestCLIOutput:
    """E2E: CLI commands produce expected output formats."""

    def test_ingest_json_output(self, tmp_path, mock_llm):
        """--json flag produces valid JSON with new stat keys."""
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A\n\nContent.")
        init_project(tmp_path, name="cli-test")

        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "deep_obsidian.cli", "ingest", str(tmp_path), "--json"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            check=False,
        )
        assert result.returncode == 0, f"CLI exited {result.returncode}: {result.stderr}"
        data = json.loads(result.stdout.strip())
        assert "added" in data
        assert "modified" in data
        assert "deleted" in data
        assert "unchanged" in data
        assert "failed" in data
        assert "elapsed_seconds" in data


class TestForgetE2E:
    """E2E: forget file-level and --all workflows."""

    def test_forget_single_file_by_relpath(self, tmp_path, mock_llm):
        """Forget a single file by relative path removes it from graph and hashes."""
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A\n\nContent A.")
        (tmp_path / "b.md").write_text("# B\n\nContent B.")
        init_project(tmp_path, name="forget-test")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))

        # Verify both files in hashes
        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "a.md" in hashes
        assert "b.md" in hashes

        # Forget a.md
        r = asyncio.run(forget(["a.md"], vault_path=str(tmp_path)))
        assert r["forgotten"] == 1
        assert r["warnings"] == []

        # a.md removed from hashes, b.md stays
        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "a.md" not in hashes
        assert "b.md" in hashes

    def test_forget_by_directory_prefix(self, tmp_path, mock_llm):
        """Forget with a directory prefix removes all files under that dir."""
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "a.md").write_text("# A")
        (tmp_path / "notes" / "b.md").write_text("# B")
        (tmp_path / "root.md").write_text("# Root")
        init_project(tmp_path, name="dir-forget")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))

        r = asyncio.run(forget(["notes"], vault_path=str(tmp_path)))
        assert r["forgotten"] == 2

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "notes/a.md" not in hashes
        assert "notes/b.md" not in hashes
        assert "root.md" in hashes

    def test_forget_all_clears_everything(self, tmp_path, mock_llm):
        """forget(all=True) clears the entire dataset."""
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        (tmp_path / "b.md").write_text("# B")
        init_project(tmp_path, name="all-forget")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))

        r = asyncio.run(forget(all=True, vault_path=str(tmp_path)))
        assert r["forgotten"] == 2
        assert r["warnings"] == []

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert hashes == {}

    def test_forget_nonexistent_target_warns(self, tmp_path, mock_llm):
        """Forgetting a file not in hashes gives a warning but doesn't crash."""
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "real.md").write_text("# Real")
        init_project(tmp_path, name="warn-forget")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))

        r = asyncio.run(forget(["nonexistent.md"], vault_path=str(tmp_path)))
        assert r["forgotten"] == 0
        assert len(r["warnings"]) == 1
        assert "not found" in r["warnings"][0]

    def test_forget_basename_match(self, tmp_path, mock_llm):
        """Forget by basename matches files in subdirectories."""
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "archive").mkdir()
        (tmp_path / "archive" / "journal.md").write_text("# Journal A")
        (tmp_path / "daily").mkdir()
        (tmp_path / "daily" / "journal.md").write_text("# Journal B")
        init_project(tmp_path, name="basename-forget")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))

        # Single basename match → forgets it
        r = asyncio.run(forget(["journal.md"], vault_path=str(tmp_path)))
        # Should have 2 matches → ambiguous, skipped with warning
        assert r["forgotten"] == 0
        assert len(r["warnings"]) == 1
        assert "matches multiple files" in r["warnings"][0]

    def test_forget_after_ingest_reenables(self, tmp_path, mock_llm):
        """Forgetting a file, then re-ingesting re-adds it."""
        from deep_obsidian.forget import forget
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        note = tmp_path / "revive.md"
        note.write_text("# Revive\n\nContent.")
        init_project(tmp_path, name="revive-forget")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))
        asyncio.run(forget(["revive.md"], vault_path=str(tmp_path)))

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "revive.md" not in hashes

        # Re-ingest re-adds it
        r = asyncio.run(ingest(str(tmp_path)))
        assert r["added"] == 1

    def test_forget_targets_and_all_mutually_exclusive(self, tmp_path, mock_llm):
        """forget with both targets and all=True raises ValueError."""
        import pytest

        from deep_obsidian.forget import forget
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="mutex-forget")

        import asyncio

        with pytest.raises(ValueError, match="both targets and --all"):
            asyncio.run(forget(["a.md"], all=True, vault_path=str(tmp_path)))

    def test_forget_no_args_raises(self, tmp_path, mock_llm):
        """forget with neither targets nor all raises ValueError."""
        import pytest

        from deep_obsidian.forget import forget
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="noargs-forget")

        import asyncio

        with pytest.raises(ValueError, match="specify target"):
            asyncio.run(forget(vault_path=str(tmp_path)))
