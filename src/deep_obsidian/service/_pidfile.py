"""PID file management for the service daemon."""

from __future__ import annotations

import os
from pathlib import Path


def pidfile_path(config_dir: Path) -> Path:
    """Return the path to the service PID file."""
    return config_dir / "service.pid"


def read_pid(config_dir: Path) -> int | None:
    """Read the PID from the PID file, or None."""
    pf = pidfile_path(config_dir)
    try:
        content = pf.read_text().strip()
        return int(content) if content.isdigit() else None
    except (FileNotFoundError, ValueError):
        return None


def write_pid(config_dir: Path, pid: int) -> None:
    """Write the PID to the PID file."""
    pf = pidfile_path(config_dir)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(pid))


def remove_pid(config_dir: Path) -> None:
    """Remove the PID file."""
    try:
        pidfile_path(config_dir).unlink()
    except FileNotFoundError:
        pass


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
