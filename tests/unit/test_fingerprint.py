"""Tests for file fingerprinting."""

from __future__ import annotations

import json

from deep_obsidian.ingest._fingerprint import (
    file_hash,
    get_data_id,
    load_hashes,
    save_hashes,
    set_data_id,
)


class TestFileHash:
    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_text("hello")
        f2 = tmp_path / "b.txt"
        f2.write_text("hello")
        assert file_hash(str(f1)) == file_hash(str(f2))

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_text("hello")
        f2 = tmp_path / "b.txt"
        f2.write_text("world")
        assert file_hash(str(f1)) != file_hash(str(f2))


class TestHashes:
    def test_load_roundtrip(self, tmp_path):
        """Stored dict is loaded as-is."""
        p = tmp_path / "hashes.json"
        data = {"note.md": {"hash": "abc123", "data_id": "uuid-1"}}
        p.write_text(json.dumps(data))
        result = load_hashes(str(p))
        assert result == data

    def test_load_missing_file_returns_empty(self, tmp_path):
        result = load_hashes(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        p = tmp_path / "hashes.json"
        p.write_text("not json{{{")
        result = load_hashes(str(p))
        assert result == {}

    def test_save_writes_dict_format(self, tmp_path):
        p = tmp_path / "hashes.json"
        mapping = {"note.md": {"hash": "abc123", "data_id": "uuid-1"}}
        save_hashes(str(p), mapping)
        loaded = json.loads(p.read_text())
        assert loaded == mapping

    def test_save_preserves_hash_without_data_id(self, tmp_path):
        p = tmp_path / "hashes.json"
        mapping = {"note.md": {"hash": "abc123"}}
        save_hashes(str(p), mapping)
        loaded = json.loads(p.read_text())
        assert loaded == mapping

    def test_get_data_id_returns_none_for_missing_file(self, tmp_path):
        p = tmp_path / "hashes.json"
        save_hashes(str(p), {"note.md": {"hash": "abc123"}})
        assert get_data_id(str(p), "note.md") is None

    def test_get_data_id_returns_none_for_missing_entry(self, tmp_path):
        p = tmp_path / "hashes.json"
        save_hashes(str(p), {"note.md": {"hash": "abc123", "data_id": "uuid-1"}})
        assert get_data_id(str(p), "other.md") is None

    def test_get_data_id_returns_value(self, tmp_path):
        p = tmp_path / "hashes.json"
        save_hashes(str(p), {"note.md": {"hash": "abc123", "data_id": "uuid-1"}})
        assert get_data_id(str(p), "note.md") == "uuid-1"

    def test_set_data_id_adds_to_existing(self, tmp_path):
        p = tmp_path / "hashes.json"
        save_hashes(str(p), {"note.md": {"hash": "abc123"}})
        set_data_id(str(p), "note.md", "uuid-new")
        result = load_hashes(str(p))
        assert result["note.md"]["data_id"] == "uuid-new"
        assert result["note.md"]["hash"] == "abc123"

    def test_set_data_id_updates_existing(self, tmp_path):
        p = tmp_path / "hashes.json"
        save_hashes(str(p), {"note.md": {"hash": "abc123", "data_id": "uuid-old"}})
        set_data_id(str(p), "note.md", "uuid-new")
        result = load_hashes(str(p))
        assert result["note.md"]["data_id"] == "uuid-new"

    def test_set_data_id_does_not_clobber_other_entries(self, tmp_path):
        p = tmp_path / "hashes.json"
        mapping = {
            "a.md": {"hash": "aaa"},
            "b.md": {"hash": "bbb", "data_id": "id-b"},
        }
        save_hashes(str(p), mapping)
        set_data_id(str(p), "a.md", "id-a")
        result = load_hashes(str(p))
        assert result["a.md"] == {"hash": "aaa", "data_id": "id-a"}
        assert result["b.md"] == {"hash": "bbb", "data_id": "id-b"}


class TestSaveHashesCrashSafety:
    """Regression coverage for the crash-safety guarantee ADR-0005 exists
    for: a process kill mid-write must never leave hashes.json truncated
    or corrupted — the reader must always see either the old complete
    content or the new complete content, never a partial write.
    """

    def test_crash_during_replace_preserves_old_content(self, tmp_path, monkeypatch):
        """If os.replace() itself fails (e.g. process killed right at the
        rename), the original file must be untouched and the temp file
        cleaned up — not left behind as ``.hashes.json.<random>.tmp``.
        """
        import os as _os

        p = tmp_path / "hashes.json"
        original = {"note.md": {"hash": "original-hash", "data_id": "uuid-orig"}}
        save_hashes(str(p), original)

        real_replace = _os.replace

        def _boom_replace(src, dst):
            raise OSError("simulated crash during os.replace")

        monkeypatch.setattr(_os, "replace", _boom_replace)

        import pytest

        with pytest.raises(OSError, match="simulated crash"):
            save_hashes(str(p), {"note.md": {"hash": "new-hash", "data_id": "uuid-new"}})

        monkeypatch.setattr(_os, "replace", real_replace)

        # Original file must still hold the OLD content, unmodified.
        assert load_hashes(str(p)) == original

        # No leftover .tmp files in the directory.
        leftovers = [f for f in _os.listdir(tmp_path) if f.endswith(".tmp")]
        assert leftovers == [], f"temp file(s) not cleaned up: {leftovers}"

    def test_crash_during_write_preserves_old_content(self, tmp_path, monkeypatch):
        """If the write to the temp file itself fails partway through
        (disk full, process killed), the original file must be
        untouched and the temp file cleaned up.
        """
        import os as _os

        p = tmp_path / "hashes.json"
        original = {"note.md": {"hash": "original-hash"}}
        save_hashes(str(p), original)

        import json as _json

        real_dumps = _json.dumps

        def _boom_dumps(*args, **kwargs):
            raise ValueError("simulated crash mid-serialization")

        monkeypatch.setattr(_json, "dumps", _boom_dumps)

        import pytest

        with pytest.raises(ValueError, match="simulated crash"):
            save_hashes(str(p), {"note.md": {"hash": "new-hash"}})

        monkeypatch.setattr(_json, "dumps", real_dumps)

        assert load_hashes(str(p)) == original
        leftovers = [f for f in _os.listdir(tmp_path) if f.endswith(".tmp")]
        assert leftovers == [], f"temp file(s) not cleaned up: {leftovers}"

    def test_first_write_crash_leaves_no_file(self, tmp_path, monkeypatch):
        """If there is no prior hashes.json yet and the very first write
        crashes, no partial/empty file should be left behind either.
        """
        import os as _os

        p = tmp_path / "hashes.json"
        assert not p.exists()

        def _boom_replace(src, dst):
            raise OSError("simulated crash on first write")

        monkeypatch.setattr(_os, "replace", _boom_replace)

        import pytest

        with pytest.raises(OSError, match="simulated crash"):
            save_hashes(str(p), {"note.md": {"hash": "h"}})

        assert not p.exists(), "a partial file must not be left behind"
