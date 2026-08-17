"""Unit tests for search helpers — word boundary and tag matching."""

from __future__ import annotations

import json
from pathlib import Path

from deep_obsidian.search import _build_source_index, _tag_matches, _word_boundary_match


class TestBuildSourceIndex:
    """_build_source_index resolves hashes.json → data_id/stem indexes.

    ADR-0014: hashes.json lives at the RESOLVED location — project level
    <config_dir>/vault/hashes.json, user level
    ~/.deep-obsidian/vaults/<hash>/hashes.json. The function takes the
    resolved path directly, so both levels must work (regression: it
    used to hardcode config_dir/vault/hashes.json, missing user-level
    state entirely).
    """

    def _write_hashes(self, hashes_path: Path) -> None:
        hashes_path.parent.mkdir(parents=True, exist_ok=True)
        hashes_path.write_text(
            json.dumps(
                {
                    "notes/a.md": {"data_id": "d1"},
                    "notes/b.md": {"data_id": "d2"},
                }
            ),
            encoding="utf-8",
        )

    def test_builds_indexes_from_hashes_path(self, tmp_path: Path) -> None:
        hashes_path = tmp_path / ".deep-obsidian" / "vault" / "hashes.json"
        self._write_hashes(hashes_path)

        by_data_id, by_stem = _build_source_index(hashes_path)

        assert by_data_id == {"d1": "notes/a.md", "d2": "notes/b.md"}
        assert by_stem["a"] == "notes/a.md"
        assert by_stem["b"] == "notes/b.md"

    def test_user_level_hashes_path_works(self, tmp_path: Path) -> None:
        """Regression: user-level state lives at vaults/<hash>/hashes.json
        — the index builder must accept that resolved path (not assume
        config_dir/vault/hashes.json).
        """
        hashes_path = tmp_path / "vaults" / "a1b2c3d4" / "hashes.json"
        self._write_hashes(hashes_path)

        by_data_id, _ = _build_source_index(hashes_path)

        assert by_data_id == {"d1": "notes/a.md", "d2": "notes/b.md"}

    def test_none_returns_empty(self) -> None:
        assert _build_source_index(None) == ({}, {})

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _build_source_index(tmp_path / "nope" / "hashes.json") == ({}, {})

    def test_missing_data_id_skipped(self, tmp_path: Path) -> None:
        hashes_path = tmp_path / "hashes.json"
        hashes_path.write_text(
            json.dumps({"notes/a.md": {}, "notes/b.md": {"data_id": "d2"}}),
            encoding="utf-8",
        )

        by_data_id, _ = _build_source_index(hashes_path)

        assert by_data_id == {"d2": "notes/b.md"}

    def test_exact_word_matches(self):
        assert not _word_boundary_match("habit", "habits are powerful")
        assert _word_boundary_match("habit", "the habit of reading")

    def test_substring_does_not_match(self):
        assert not _word_boundary_match("habit", "inhabited")
        assert not _word_boundary_match("habit", "habitual")

    def test_case_insensitive(self):
        assert _word_boundary_match("Habit", "a HABIT forms")

    def test_chinese_tag_behavior(self):
        # Regression: tags containing CJK characters have no word-boundary
        # concept under Python's \w (CJK ideographs count as word chars),
        # so a pure-CJK tag embedded in CJK text used to silently fail to
        # match via the ASCII word-boundary regex. _word_boundary_match
        # now falls back to a plain substring check for CJK tags.
        assert _word_boundary_match("习惯", "如何养成习惯")
        assert _word_boundary_match("习惯", "习惯 如何养成")
        assert _word_boundary_match("习惯", "如何养成 习惯")
        assert not _word_boundary_match("习惯", "没有相关内容")

    def test_tag_with_regex_chars_escaped(self):
        # Tags containing regex special chars must not break or over-match
        assert _word_boundary_match("c++", "learn c++ today")
        assert _word_boundary_match("a.b", "see a.b here")
        assert not _word_boundary_match("a.b", "see axb here")

    def test_empty_text(self):
        assert not _word_boundary_match("habit", "")

    def test_empty_tag(self):
        assert not _word_boundary_match("", "some text")


class TestTagMatches:
    def test_structured_tags_metadata(self):
        result = type("R", (), {"tags": ["habit", "psychology"]})()
        assert _tag_matches("habit", "any text", result)
        assert not _tag_matches("learning", "any text", result)

    def test_structured_tags_via_metadata_dict(self):
        result = type("R", (), {"tags": None, "metadata": {"tags": ["focus"]}})()
        assert _tag_matches("focus", "text", result)

    def test_fallback_to_text_search(self):
        result = type("R", (), {"tags": None, "metadata": {}})()
        assert _tag_matches("habit", "the habit of reading", result)
        assert not _tag_matches("habit", "inhabited", result)

    def test_no_tags_no_text_match(self):
        result = type("R", (), {"tags": None, "metadata": {}})()
        assert not _tag_matches("missing", "no match here", result)

    def test_no_attributes_at_all(self):
        result = object()
        assert _tag_matches("habit", "the habit text", result)
