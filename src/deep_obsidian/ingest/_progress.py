"""Progress persistence — track which files have been ingested."""

import json
import os
from pathlib import Path


class ProgressStore:
    """Persistent record of completed file ingestions.

    Stores a JSON array of completed file names at ``filepath``.
    Each call to ``mark_done`` atomically writes the updated list.
    """

    def __init__(self, filepath: str) -> None:
        self._filepath = Path(filepath)
        self._completed: set[str] = self._load()

    @property
    def completed(self) -> set[str]:
        return self._completed.copy()

    def is_completed(self, filename: str) -> bool:
        return filename in self._completed

    def mark_done(self, filename: str) -> None:
        self._completed.add(filename)
        self._persist()

    def reset(self) -> None:
        self._completed.clear()
        try:
            os.remove(str(self._filepath))
        except FileNotFoundError:
            pass

    def stats(self) -> tuple[int, int]:
        """Return (completed_count, total_count).

        Not yet implemented — ProgressStore has no inventory of all
        md files in the vault, so the total cannot be computed here.
        """
        raise NotImplementedError("stats() is not yet implemented")

    # ── internal ──

    def _load(self) -> set[str]:
        try:
            with open(self._filepath) as f:
                return set(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

    def _persist(self) -> None:
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self._filepath, "w") as f:
            json.dump(sorted(self._completed), f)
