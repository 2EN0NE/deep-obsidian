"""Regression tests for mid-ingest interrupt resilience and stale-hashes guard.

Bug 1 (interrupt): ``save_hashes()`` was only called ONCE, after the entire Phase 1
add/update loop finished. If the process is interrupted (Ctrl+C, kill,
crash) partway through that loop — very plausible for a large vault
where each file requires a network call — every file successfully
``cognee.add()``-ed so far is lost from ``hashes.json``. The next
``ingest()`` run then treats those files as brand new, re-adding them
with a *different* data_id — duplicating them in Cognee's graph on
top of wasting the already-completed work.

Fix: persist the hash/data_id for a file immediately after it is
added/updated, not only after the whole batch completes.

Bug 2 (stale hashes): ``hashes.json`` was trusted blindly. If the
Cognee database is wiped or replaced (e.g. venv rebuild, clone to a
different machine), the file hashes still match, so ``ingest()``
returns ``unchanged: N`` without actually checking whether the
dataset still exists in Cognee. The next search/query then fails
with "Dataset not found".

Fix: when all files are skipped based on stored hashes, verify the
dataset still exists in Cognee before returning early. If the
dataset is missing, force a full re-ingestion.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch


class _SimulatedInterrupt(KeyboardInterrupt):
    """Stand-in for a real Ctrl+C / SIGINT/SIGTERM during ingest."""


class TestInterruptMidLoopPreservesProgress:
    def test_files_added_before_interrupt_are_persisted(self, tmp_path, mock_llm):
        """Interrupting after N of M files must not lose the N completed ones."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        for i in range(1, 5):
            (tmp_path / f"note{i}.md").write_text(f"# Note {i}\n\nContent {i}.")
        init_project(tmp_path, name="test-vault")

        def on_progress(current: int, total: int, desc: str) -> None:
            if current == 2:
                raise _SimulatedInterrupt("simulated Ctrl+C at file 2/4")

        with __import__("pytest").raises(_SimulatedInterrupt):
            asyncio.run(ingest(str(tmp_path), on_progress=on_progress))

        # The first 2 files completed cognee.add() before the interrupt —
        # their hash/data_id must already be on disk.
        hashes_path = tmp_path / ".deep-obsidian" / "vault" / "hashes.json"
        stored = load_hashes(str(hashes_path))
        assert len(stored) == 2, (
            f"Expected the 2 files processed before interrupt to be persisted, "
            f"got {len(stored)}: {list(stored.keys())}"
        )
        for rel, entry in stored.items():
            assert entry.get("data_id"), f"{rel} missing data_id after interrupt"

    def test_resume_after_interrupt_does_not_readd_completed_files(self, tmp_path, mock_llm):
        """Re-running ingest() after a mid-loop interrupt must only process
        the files that never completed — not redo (and duplicate) the ones
        that already succeeded."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        for i in range(1, 5):
            (tmp_path / f"note{i}.md").write_text(f"# Note {i}\n\nContent {i}.")
        init_project(tmp_path, name="test-vault")

        def on_progress(current: int, total: int, desc: str) -> None:
            if current == 2:
                raise _SimulatedInterrupt("simulated Ctrl+C at file 2/4")

        with __import__("pytest").raises(_SimulatedInterrupt):
            asyncio.run(ingest(str(tmp_path), on_progress=on_progress))

        # Resume: only the remaining 2 files should be added; the first 2
        # must be reported as unchanged (i.e. not re-added / duplicated).
        result = asyncio.run(ingest(str(tmp_path)))
        assert result["added"] == 2, f"Expected 2 remaining files added, got {result}"
        assert result["unchanged"] == 2, f"Expected 2 already-done files skipped, got {result}"


class TestStaleHashesDetection:
    """When hashes.json is stale (dataset doesn't exist in Cognee), ingest
    must detect it and force re-ingestion instead of silently returning
    "all unchanged"."""

    def test_stale_hashes_forces_full_reingestion(self, tmp_path, mock_llm):
        """Ingest with valid hashes.json but missing dataset must re-add all files."""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import save_hashes
        from deep_obsidian.settings import init_project

        for i in range(1, 4):
            (tmp_path / f"note{i}.md").write_text(f"# Note {i}\n\nContent {i}.")
        init_project(tmp_path, name="test-vault")

        # Create a stale hashes.json — has entries with data_ids, but the
        # dataset they refer to does NOT exist in Cognee (simulate by
        # making list_datasets() return an empty list or only unrelated
        # datasets).
        stale_hashes: dict[str, dict] = {}
        from deep_obsidian.ingest._fingerprint import file_hash

        for fp in sorted(tmp_path.glob("note*.md")):
            rel = str(fp.relative_to(tmp_path))
            stale_hashes[rel] = {
                "hash": file_hash(str(fp)),
                "data_id": "11111111-1111-1111-1111-111111111111",
            }
        hashes_path = tmp_path / ".deep-obsidian" / "vault" / "hashes.json"
        save_hashes(str(hashes_path), stale_hashes)

        # Simulate: dataset "test-vault" doesn't exist in Cognee
        async def _fake_list_other_datasets():
            class _FakeDS:
                name = "some-other-dataset"
                id = "other-id"

            return [_FakeDS()]

        with patch("cognee.datasets.list_datasets", new=_fake_list_other_datasets):
            result = asyncio.run(ingest(str(tmp_path)))

        # All 3 files should have been force-re-ingested, not skipped.
        assert result["added"] == 3, f"Expected 3 files force-re-ingested, got {result}"
        assert result["unchanged"] == 0, f"Expected 0 unchanged, got {result}"

        # A warning should indicate the stale hashes were detected.
        assert any(
            "stale" in w.lower() or "not found" in w.lower() for w in result.get("warnings", [])
        ), f"Expected a stale-hashes warning, got: {result.get('warnings', [])}"
