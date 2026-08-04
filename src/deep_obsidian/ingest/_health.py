"""Pre-ingest health checks — lock cleanup, Cognee readiness verifications."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

# A lock older than this is considered stale and safe to clear.
_STALE_LOCK_SECONDS = 30 * 60  # 30 minutes


def _find_lock_file(vault_path: str) -> Path | None:
    """Locate the Ladybug graph database lock file for a vault."""
    candidate = Path(vault_path) / ".cognee" / "databases" / "cognee_graph_ladybug" / "LOCK"
    if candidate.exists():
        return candidate
    return None


def clear_ladybug_lock(vault_path: str) -> bool:
    """Detect and clear a stale Ladybug lock file.

    A lock is considered stale when:
    - The process that owns it no longer exists, OR
    - The lock file has not been touched for ``_STALE_LOCK_SECONDS``.

    Returns True if a lock was found and cleared.
    """
    lock_file = _find_lock_file(vault_path)
    if lock_file is None:
        return False

    # Parse owner PID
    pid: int | None = None
    try:
        content = lock_file.read_text().strip()
        pid = int(content) if content.isdigit() else None
    except (ValueError, OSError):
        pass

    # Decide whether the lock is stale
    is_stale = False

    if pid is not None and pid == os.getpid():
        # Our own lock — safe to clear.
        is_stale = True
    elif pid is not None:
        try:
            os.kill(pid, 0)  # process exists
        except OSError:
            is_stale = True  # process is gone
        else:
            # Process exists — check lock age
            try:
                age = time.time() - lock_file.stat().st_mtime
                if age > _STALE_LOCK_SECONDS:
                    is_stale = True
            except OSError:
                is_stale = True
    else:
        # No PID in the lock file — stale.
        is_stale = True

    if not is_stale:
        return False  # fresh lock held by a living process — leave it alone

    # Clear the stale lock — send SIGTERM (graceful) rather than
    # SIGKILL as an additional safety net against PID reuse.
    if pid is not None and pid != os.getpid():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass  # process already gone

    try:
        lock_file.unlink()
        return True
    except OSError:
        return False
