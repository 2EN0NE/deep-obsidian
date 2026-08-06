"""Tests for _match_target — file path matching for forget."""

from __future__ import annotations

from deep_obsidian.forget import _match_target


class TestMatchTargetExact:
    def test_exact_match_returns_single(self, tmp_path):
        indexed = {"notes/Justice.md": "uuid-1", "Books/History.md": "uuid-2"}
        matched, reason = _match_target("notes/Justice.md", indexed, tmp_path)
        assert matched == ["notes/Justice.md"]
        assert reason == "exact"

    def test_exact_match_not_found_returns_empty(self, tmp_path):
        indexed = {"notes/Justice.md": "uuid-1"}
        matched, reason = _match_target("nonexistent.md", indexed, tmp_path)
        assert matched == []
        assert reason == "none"


class TestMatchTargetDirectoryPrefix:
    def test_directory_prefix_matches_all_files_under(self, tmp_path):
        indexed = {
            "notes/daily/2024-01.md": "uuid-1",
            "notes/daily/2024-02.md": "uuid-2",
            "notes/weekly/summary.md": "uuid-3",
            "Books/readme.md": "uuid-4",
        }
        matched, reason = _match_target("notes/daily", indexed, tmp_path)
        assert sorted(matched) == ["notes/daily/2024-01.md", "notes/daily/2024-02.md"]
        assert reason == "directory"

    def test_directory_prefix_with_trailing_slash(self, tmp_path):
        indexed = {
            "notes/daily/2024-01.md": "uuid-1",
            "notes/daily/2024-02.md": "uuid-2",
        }
        matched, reason = _match_target("notes/daily/", indexed, tmp_path)
        assert sorted(matched) == ["notes/daily/2024-01.md", "notes/daily/2024-02.md"]
        assert reason == "directory"

    def test_directory_prefix_does_not_match_partial_name(self, tmp_path):
        """'note' should not match 'notes/daily.md' because prefix becomes 'note/'."""
        indexed = {"notes/daily.md": "uuid-1", "notebook/journal.md": "uuid-2"}
        matched, reason = _match_target("note", indexed, tmp_path)
        # Falls through to basename: "note" ≠ "daily.md" ≠ "journal.md"
        assert matched == []
        assert reason == "none"

    def test_directory_prefix_exact_takes_priority(self, tmp_path):
        """Exact match wins over directory prefix."""
        indexed = {"Books": "uuid-1", "Books/Readme.md": "uuid-2"}
        matched, reason = _match_target("Books", indexed, tmp_path)
        assert matched == ["Books"]
        assert reason == "exact"


class TestMatchTargetBasename:
    def test_basename_match_finds_file_in_subdirs(self, tmp_path):
        indexed = {
            "notes/daily/2024.md": "uuid-1",
            "archive/2024.md": "uuid-2",
        }
        matched, reason = _match_target("2024.md", indexed, tmp_path)
        assert sorted(matched) == ["archive/2024.md", "notes/daily/2024.md"]
        assert reason == "basename"

    def test_basename_single_match(self, tmp_path):
        indexed = {"notes/unique.md": "uuid-1", "Books/History.md": "uuid-2"}
        matched, reason = _match_target("unique.md", indexed, tmp_path)
        assert matched == ["notes/unique.md"]
        assert reason == "basename"

    def test_basename_no_match(self, tmp_path):
        indexed = {"notes/a.md": "uuid-1"}
        matched, reason = _match_target("b.md", indexed, tmp_path)
        assert matched == []
        assert reason == "none"


class TestMatchTargetAbsolutePath:
    def test_absolute_path_inside_project(self, tmp_path):
        project_root = tmp_path.resolve()
        indexed = {"notes/Justice.md": "uuid-1"}
        abs_target = str(project_root / "notes" / "Justice.md")
        matched, reason = _match_target(abs_target, indexed, project_root)
        assert matched == ["notes/Justice.md"]
        assert reason == "exact"

    def test_absolute_path_outside_project(self, tmp_path):
        project_root = tmp_path.resolve()
        indexed = {"notes/Justice.md": "uuid-1"}
        matched, reason = _match_target("/etc/passwd", indexed, project_root)
        assert matched == []
        assert reason == "none"


class TestMatchTargetEdgeCases:
    def test_empty_indexed(self, tmp_path):
        matched, reason = _match_target("anything.md", {}, tmp_path)
        assert matched == []
        assert reason == "none"

    def test_data_id_is_none_still_matches(self, tmp_path):
        """_match_target only uses keys of indexed dict, values can be None."""
        indexed = {"notes/Journal.md": None}
        matched, reason = _match_target("notes/Journal.md", indexed, tmp_path)
        assert matched == ["notes/Journal.md"]
        assert reason == "exact"


class TestForgetAllScope:
    """Regression: ``_forget_all`` must NOT pass ``everything=True``.

    cognee.forget()'s ``everything=True`` flag deletes *every* dataset the
    Cognee user owns and explicitly ignores the ``dataset``/``dataset_id``
    arguments (see cognee's own docstring: "Ignores data_id, dataset, and
    dataset_id"). ``deep-obsidian forget --all`` is documented (CONTEXT.md)
    as clearing *one* dataset, not every vault sharing this machine's
    Cognee installation. Passing both together silently wiped every other
    project's knowledge graph the first time any one project ran
    ``forget --all`` — verified against a real cognee==1.4.1 install.
    """

    def test_forget_all_does_not_pass_everything_flag(self, tmp_path, monkeypatch):
        import asyncio

        from deep_obsidian.forget import forget
        from deep_obsidian.ingest._fingerprint import save_hashes
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="scope-test")
        hashes_path = tmp_path / ".deep-obsidian" / "hashes.json"
        save_hashes(str(hashes_path), {"a.md": {"hash": "h1", "data_id": "id-1"}})

        calls: list[dict] = []

        async def _fake_forget(**kwargs):
            calls.append(kwargs)
            return None

        monkeypatch.setattr("deep_obsidian.forget.cognee.forget", _fake_forget)
        monkeypatch.setattr("deep_obsidian.forget.clear_ladybug_lock", lambda *_a, **_k: None)

        asyncio.run(forget(all=True, vault_path=str(tmp_path)))

        assert len(calls) == 1
        assert calls[0]["dataset"] == "scope-test"
        assert not calls[0].get("everything"), (
            "forget(all=True) must scope to this project's dataset only — "
            "passing everything=True wipes every dataset the Cognee user owns, "
            "regardless of the dataset kwarg."
        )
