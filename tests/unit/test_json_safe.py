"""Tests for _json_safe — YAML datetime serialization for Cognee."""

from __future__ import annotations

from datetime import UTC, date, datetime

from deep_obsidian.ingest import _json_safe


class TestJsonSafe:
    def test_datetime_converts_to_iso(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        assert _json_safe(dt) == "2024-01-15T10:30:00+00:00"

    def test_date_converts_to_iso(self):
        d = date(2024, 1, 15)
        assert _json_safe(d) == "2024-01-15"

    def test_naive_datetime_converts_to_iso(self):
        dt = datetime(2024, 6, 1, 12, 0, 0)
        assert _json_safe(dt) == "2024-06-01T12:00:00"

    def test_plain_string_passthrough(self):
        assert _json_safe("hello") == "hello"

    def test_int_passthrough(self):
        assert _json_safe(42) == 42

    def test_none_passthrough(self):
        assert _json_safe(None) is None

    def test_float_passthrough(self):
        assert _json_safe(3.14) == 3.14

    def test_bool_passthrough(self):
        assert _json_safe(True)
        assert not _json_safe(False)

    def test_nested_dict_with_dates(self):
        data = {
            "title": "My Note",
            "created": date(2024, 3, 10),
            "metadata": {
                "updated": datetime(2024, 6, 15, 8, 0, 0),
                "tags": ["habit", "psychology"],
            },
        }
        result = _json_safe(data)
        assert result == {
            "title": "My Note",
            "created": "2024-03-10",
            "metadata": {
                "updated": "2024-06-15T08:00:00",
                "tags": ["habit", "psychology"],
            },
        }

    def test_list_with_datetimes(self):
        data = [datetime(2024, 1, 1), "text", date(2024, 12, 31)]
        result = _json_safe(data)
        assert result == ["2024-01-01T00:00:00", "text", "2024-12-31"]

    def test_tuple_with_dates(self):
        data = (date(2024, 5, 1), "label")
        result = _json_safe(data)
        assert result == ["2024-05-01", "label"]

    def test_empty_dict(self):
        assert _json_safe({}) == {}

    def test_empty_list(self):
        assert _json_safe([]) == []

    def test_deeply_nested_structure(self):
        data = {
            "entries": [
                {"day": date(2024, 1, 1)},
                {"day": date(2024, 1, 2)},
            ],
        }
        result = _json_safe(data)
        assert result == {
            "entries": [
                {"day": "2024-01-01"},
                {"day": "2024-01-02"},
            ],
        }

    def test_mixed_types_preserved(self):
        """Non-date types in mixed collections are passed through untouched."""
        data = {
            "count": 7,
            "active": True,
            "name": "test",
            "when": date(2024, 9, 1),
        }
        result: dict = _json_safe(data)  # type: ignore[assignment]
        assert result["count"] == 7
        assert result["active"]
        assert result["name"] == "test"
        assert result["when"] == "2024-09-01"

    def test_json_serializable_after_conversion(self):
        """Result of _json_safe should be directly json.dumps-able."""
        import json

        data = {
            "frontmatter": {
                "date": date(2024, 2, 14),
                "updated": datetime(2024, 8, 1, 14, 30, 0, tzinfo=UTC),
            },
            "tags": ["test"],
        }
        safe = _json_safe(data)
        # Should not raise
        dumped = json.dumps(safe)
        assert "2024-02-14" in dumped
        assert "2024-08-01T14:30:00+00:00" in dumped
