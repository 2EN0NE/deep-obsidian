"""Cross-process ingest progress state + single-instance lock.

Persists ``.deep-obsidian/progress.json`` so that other processes (the
``status`` command, primarily) can observe an in-progress ``ingest()``
run without a live connection to it. The same file doubles as a
single-instance lock: only one ingest may hold it per project at a
time.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_FILENAME = "progress.json"


class IngestAlreadyRunningError(RuntimeError):
    """Raised by ``acquire()`` when another live ingest already holds the lock."""

    def __init__(self, state: dict):
        self.state = state
        super().__init__(
            f"Another ingest is already running for dataset '{state.get('dataset')}' "
            f"(PID {state.get('pid')}, phase: {state.get('phase')})."
        )


def _progress_path(project_root: Path) -> Path:
    return Path(project_root) / ".deep-obsidian" / _FILENAME


def read_state(project_root: Path) -> dict | None:
    """Read the raw progress state, or None if no ingest is tracked."""
    path = _progress_path(project_root)
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None


def _atomic_write(path: Path, state: dict) -> None:
    """Write *state* to *path* atomically (temp file + ``os.replace``),
    so a process kill mid-write can never leave the file truncated or
    corrupted — mirrors ``_fingerprint.py::save_hashes``.
    """
    import tempfile

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(state, indent=2))
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class ProgressHandle:
    """Context manager for an acquired progress/lock file.

    Deletes the file on exit regardless of how the ``with`` block
    exits (normal return or exception).
    """

    def __init__(self, path: Path, state: dict):
        self._path = path
        self._state = dict(state)

    def update(self, phase: str, current: int, total: int, current_file: str = "") -> None:
        """Overwrite the persisted state with new phase/progress fields."""
        self._state["phase"] = phase
        self._state["current"] = current
        self._state["total"] = total
        self._state["current_file"] = current_file
        _atomic_write(self._path, self._state)

    def __enter__(self) -> ProgressHandle:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False

    def release(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


def is_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is alive.

    Not imported from ``service/_pidfile.py``: ``ingest`` must not
    depend on ``service`` — ``service`` already depends on ``ingest``
    (``service/__init__.py`` imports ``ingest()``), so importing
    ``service._pidfile`` from here would create a circular import once
    ``acquire()`` is wired into ``ingest/__init__.py`` (importing the
    ``deep_obsidian.service`` package always runs its ``__init__.py``
    first, which imports ``ingest`` back). The function itself is a
    five-line OS primitive, cheap enough to duplicate rather than risk
    the cycle. ``status.py`` imports this copy (safe: it doesn't create
    a cycle in that direction) rather than duplicating it a third time.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _try_create(path: Path, state: dict) -> bool:
    """Exclusively create *path* with *state* as its initial content.

    Returns False (without raising) if the file already exists.
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(state, indent=2))
    return True


def acquire(
    project_root: Path, dataset: str, total: int, *, now: float | None = None
) -> ProgressHandle:
    """Exclusively acquire the progress/lock file for a new ingest run.

    Raises ``IngestAlreadyRunningError`` if another live ingest already
    holds the lock. A lock left behind by a dead process (crash,
    SIGKILL) is cleaned up and re-acquired automatically.

    *now* is an optional timestamp override for ``started_at`` — only
    exposed for tests that need deterministic timestamps without
    monkeypatching ``time.time``.
    """
    path = _progress_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    initial_state = {
        "pid": os.getpid(),
        "dataset": dataset,
        "phase": "starting",
        "current": 0,
        "total": total,
        "current_file": "",
        "started_at": now if now is not None else time.time(),
    }

    if _try_create(path, initial_state):
        return ProgressHandle(path, initial_state)

    existing = read_state(project_root)
    if existing is not None:
        pid = existing.get("pid")
        if isinstance(pid, int) and is_process_alive(pid):
            raise IngestAlreadyRunningError(existing)

    # Stale lock (dead pid, or unreadable/corrupt state) — clean up and
    # retry once, mirroring service.start_service()'s pattern.
    try:
        path.unlink()
    except FileNotFoundError:
        pass

    if not _try_create(path, initial_state):
        existing = read_state(project_root)
        if existing is not None:
            pid = existing.get("pid")
            if isinstance(pid, int) and is_process_alive(pid):
                raise IngestAlreadyRunningError(existing)
        raise RuntimeError(f"Could not acquire ingest lock at {path}")

    return ProgressHandle(path, initial_state)
