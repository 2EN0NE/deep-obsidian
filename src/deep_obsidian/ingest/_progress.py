"""Terminal progress card for ingest — live-updating ANSI UI.

Renders a compact text block on stderr that shows progress percentage,
current file, elapsed time, and action counts.  Uses ANSI escape
sequences to update in-place so the terminal doesn't scroll.

Only active when stderr is a TTY; otherwise silently degrades to
no output (the final summary from the CLI is still printed).
"""

from __future__ import annotations

import sys as _sys
import time as _time


class ProgressCard:
    """Live-updating terminal progress display.

    Usage::

        card = ProgressCard("my-vault", "my-dataset")
        card.start_scan(150)

        for file in files:
            card.update(current, total, f"{relpath} (added)")

        card.start_cognify()
        # ... cognify runs ...
        card.finish(added=5, modified=0, skipped=1, failed=0)
    """

    def __init__(self, vault_name: str, dataset: str):
        self._vault = vault_name
        self._dataset = dataset
        self._start = _time.monotonic()
        self._current = 0
        self._total = 0
        self._current_file = ""
        self._added = 0
        self._modified = 0
        self._skipped = 0
        self._failed = 0
        self._phase = "🔍 扫描中…"
        self._lines = 0
        self._active = _sys.stderr.isatty()

    # ── public API ──

    def start_scan(self, total: int) -> None:
        self._phase = "🔍 扫描笔记"
        self._total = total
        self._render()

    def start_process(self, total: int) -> None:
        self._phase = "📄 Phase 1/2: 添加文件"
        self._current = 0
        self._total = total
        self._render()

    def update(self, current: int, total: int, description: str) -> None:
        self._current = current
        self._total = total

        # ── parse action from description suffix ──
        if "(skipped)" in description:
            self._skipped += 1
        elif "(added)" in description:
            self._added += 1
        elif "(modified)" in description:
            self._modified += 1
        elif "FAILED" in description:
            self._failed += 1

        # ── extract filename (strip the action suffix) ──
        self._current_file = description.rsplit(" (", 1)[0] if " (" in description else description

        self._render()

    def start_cognify(self) -> None:
        self._phase = "🧠 Phase 2/2: 语义推理 (cognify)"
        self._current_file = ""
        self._render()

    def finish(
        self,
        added: int = 0,
        modified: int = 0,
        skipped: int = 0,
        failed: int = 0,
    ) -> None:
        """Clear the progress display and print a completion line.

        The counts passed here override the internally tracked values
        because the card may not have seen every action (e.g. it was
        created mid-way or some phases bypass the callback).
        """
        self._clear()

        if not self._active:
            return

        elapsed = _time.monotonic() - self._start
        total = added + modified + skipped + failed
        parts = [f"✅ {total} files"]
        if added:
            parts.append(f"+{added}")
        if modified:
            parts.append(f"~{modified}")
        if skipped:
            parts.append(f"⏭️ {skipped}")
        if failed:
            parts.append(f"❌ {failed}")
        parts.append(_format_time(elapsed))

        _sys.stderr.write(" · ".join(parts) + "\n")
        _sys.stderr.flush()

    # ── internal ──

    def _render(self) -> None:
        if not self._active:
            return

        self._clear()

        elapsed = _time.monotonic() - self._start
        pct = min(self._current / self._total * 100, 100) if self._total > 0 else 0

        bar_width = 20
        try:
            filled = int(bar_width * self._current / self._total) if self._total > 0 else 0
        except (TypeError, ValueError, ZeroDivisionError):
            filled = 0
        bar = "█" * filled + "░" * (bar_width - filled)

        top = (
            f"{self._phase}  {bar} {pct:4.0f}%"
            f" · {self._current}/{self._total}"
            f" · {_format_time(elapsed)}"
        )
        file_line = f"📄 {_truncate(self._current_file, 50)}" if self._current_file else ""
        counters = f"✅ +{self._added}  📝 ~{self._modified}  ⏭️ {self._skipped}  ❌ {self._failed}"

        lines = [top]
        if file_line:
            lines.append(file_line)
        lines.append(counters)

        _sys.stderr.write("\n".join(lines) + "\n")
        _sys.stderr.flush()
        self._lines = len(lines)

    def _clear(self) -> None:
        if self._lines > 0:
            _sys.stderr.write(f"\033[{self._lines}A\033[J")
            _sys.stderr.flush()
            self._lines = 0


# ── helpers ──


def _truncate(s: str, max_visual: int) -> str:
    """Truncate *s* to fit within *max_visual* columns, adding '…'."""
    if not s:
        return s
    visual = 0
    chars = list(s)
    for i, ch in enumerate(chars):
        cw = _char_width(ch)
        # Reserve 1 column for potential "…" UNLESS this is the last char
        needed = cw if i == len(chars) - 1 else cw + 1
        if visual + needed > max_visual:
            # Would overflow — stop here with ellipsis
            result: list[str] = chars[:i]
            result.append("…")
            return "".join(result)
        visual += cw
    # All chars fit
    return s


def _char_width(ch: str) -> int:
    """Return 2 for CJK characters, 1 otherwise."""
    cp = ord(ch)
    if (
        (0x1100 <= cp <= 0x115F)  # Hangul Jamo
        or (0x2329 <= cp <= 0x232A)  # angle brackets
        or (0x2E80 <= cp <= 0xA4CF)  # CJK radicals … Yi
        or (0xA960 <= cp <= 0xA97C)  # Hangul
        or (0xAC00 <= cp <= 0xD7A3)  # Hangul syllables
        or (0xF900 <= cp <= 0xFAFF)  # CJK Compatibility
        or (0xFE10 <= cp <= 0xFE19)  # vertical forms
        or (0xFE30 <= cp <= 0xFE6F)  # CJK Compatibility Forms
        or (0xFF01 <= cp <= 0xFF60)  # fullwidth forms
        or (0xFFE0 <= cp <= 0xFFE6)  # fullwidth signs
        or (0x1B000 <= cp <= 0x1B2FF)  # Kana Supplement
        or (0x1F300 <= cp <= 0x1F64F)  # Emoticons
        or (0x20000 <= cp <= 0x2FFFF)  # CJK Extension B+
        or (0x30000 <= cp <= 0x3FFFF)  # CJK Extension G+
    ):
        return 2
    return 1


def _format_time(seconds: float) -> str:
    try:
        m, s = divmod(int(seconds), 60)
    except (TypeError, ValueError):
        return "--:--"
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m:02d}:{s:02d}"
