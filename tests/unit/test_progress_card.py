"""Unit tests for deep_obsidian.ingest._progress — ProgressCard and helpers."""

from __future__ import annotations

import sys
from unittest.mock import patch

from deep_obsidian.ingest._progress import (
    ProgressCard,
    _char_width,
    _format_time,
    _truncate,
)

# ── _truncate ──


class TestTruncate:
    def test_ascii_fits(self) -> None:
        assert _truncate("hello", 10) == "hello"

    def test_ascii_exceeds(self) -> None:
        assert _truncate("hello world", 8) == "hello w…"

    def test_empty(self) -> None:
        assert _truncate("", 10) == ""

    def test_cjk_fits(self) -> None:
        assert _truncate("你好", 4) == "你好"

    def test_cjk_exceeds(self) -> None:
        # "你好世界" = 8 cols, truncate to 5 → "你好…" (4 + 1)
        result = _truncate("你好世界", 5)
        assert result == "你好…"

    def test_mixed_ascii_cjk(self) -> None:
        # "a你b好" = 1+2+1+2 = 6 cols
        assert _truncate("a你b好", 6) == "a你b好"
        # truncate to 4 → "a你…" (1+2+1)
        assert _truncate("a你b好", 4) == "a你…"


# ── _char_width ──


class TestCharWidth:
    def test_ascii(self) -> None:
        assert _char_width("a") == 1
        assert _char_width("Z") == 1
        assert _char_width("1") == 1

    def test_cjk(self) -> None:
        assert _char_width("中") == 2
        assert _char_width("文") == 2
        assert _char_width("日") == 2

    def test_emoji(self) -> None:
        # Many emoji fall in 0x1F300–0x1F64F
        assert _char_width("😀") == 2


# ── _format_time ──


class TestFormatTime:
    def test_seconds(self) -> None:
        assert _format_time(0) == "00:00"
        assert _format_time(5) == "00:05"

    def test_minutes(self) -> None:
        assert _format_time(65) == "01:05"
        assert _format_time(125) == "02:05"

    def test_hours(self) -> None:
        assert _format_time(3661) == "1h01m01s"

    def test_invalid(self) -> None:
        assert _format_time(float("nan")) == "--:--"


# ── ProgressCard ──


class TestProgressCard:
    """Test ProgressCard output by capturing stderr."""

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_renders_scan_phase(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        with patch.object(sys.stderr, "write") as mock_write:
            card.start_scan(10)
            # Should have written at least one multi-line block
            assert mock_write.call_count >= 1

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_renders_update(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        with patch.object(sys.stderr, "write") as mock_write:
            card.update(3, 10, "Books/test.md (added)")
            output = "".join(c[0][0] for c in mock_write.call_args_list)
            assert "30%" in output or "📄" in output
            assert "Books/test.md" in output

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_parse_skipped(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        # Card starts with 0 skipped
        assert card._skipped == 0
        with patch.object(sys.stderr, "write"):
            card.update(1, 10, "Books/skip.md (skipped)")
        assert card._skipped == 1
        assert card._added == 0

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_parse_added(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        with patch.object(sys.stderr, "write"):
            card.update(1, 10, "Books/add.md (added)")
        assert card._added == 1

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_parse_modified(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        with patch.object(sys.stderr, "write"):
            card.update(1, 10, "Books/mod.md (modified)")
        assert card._modified == 1

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_parse_failed(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        with patch.object(sys.stderr, "write"):
            card.update(1, 10, "Books/bad.md FAILED: something")
        assert card._failed == 1

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_start_cognify(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        card.start_cognify()
        assert "cognify" in card._phase

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_finish_prints_summary(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        with patch.object(sys.stderr, "write") as mock_write:
            card.finish(added=5, modified=1, skipped=2, failed=0)
        output = "".join(c[0][0] for c in mock_write.call_args_list)
        assert "5" in output
        assert "8 files" in output  # total = 5+1+2+0

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_finish_with_counts(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        with patch.object(sys.stderr, "write") as mock_write:
            card.finish(added=3, modified=0, skipped=7, failed=1)
        output = "".join(c[0][0] for c in mock_write.call_args_list)
        assert "+3" in output
        assert "⏭️ 7" in output
        assert "❌ 1" in output

    @patch.object(sys.stderr, "isatty", return_value=False)
    def test_no_output_when_not_tty(self, _mock_tty) -> None:
        card = ProgressCard("test-vault", "test-ds")
        with patch.object(sys.stderr, "write") as mock_write:
            card.start_scan(10)
            card.update(1, 10, "test.md (added)")
            card.start_cognify()
            card.finish(added=1)
        # No writes to stderr when not a TTY
        assert mock_write.call_count == 0

    @patch.object(sys.stderr, "isatty", return_value=True)
    def test_clear_on_second_render(self, _mock_tty) -> None:
        """Each _render() call should clear previous output lines via ANSI."""
        card = ProgressCard("test-vault", "test-ds")
        card.start_scan(10)
        assert card._lines > 0, "Should have rendered scan phase"
        # Second render should clear then redraw
        with patch.object(sys.stderr, "write") as mock_write:
            card.update(1, 10, "test.md (added)")
        # After first render, _lines > 0, so second _render should call
        # _clear() which writes the ANSI escape via _sys.stderr.write
        all_output = "".join(c.args[0] if c.args else "" for c in mock_write.call_args_list)
        # ANSI clear sequence: ESC [ N A ESC [ J
        assert "\x1b[" in all_output, f"Expected ANSI clear, got: {all_output!r}"
        # After second render, lines count should be the same or updated
        assert card._lines > 0
