"""File fingerprinting for incremental ingestion.

Stores a dict per file: {"hash": "<sha256>", "data_id": "<uuid>"}.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# ── hash computation ──


def file_hash(filepath: str | Path) -> str:
    """Compute SHA-256 hash of a file's contents (first 16 hex chars)."""
    return hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:16]


# ── persist / load ──


def load_hashes(hashes_path: str) -> dict[str, dict]:
    """Load the stored file→metadata mapping."""
    try:
        return json.loads(Path(hashes_path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_hashes(hashes_path: str, mapping: dict[str, dict]) -> None:
    """Persist file→metadata mapping atomically.

    Writes to a temp file in the same directory then renames it into
    place, so a process kill mid-write can never leave ``hashes_path``
    truncated or corrupted — the reader always sees either the old
    complete content or the new complete content.
    """
    import os
    import tempfile

    path = Path(hashes_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(mapping, indent=2))
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ── data_id helpers ──


def get_data_id(hashes_path: str, relpath: str) -> str | None:
    """Return the Cognee data_id for *relpath*, or None."""
    hashes = load_hashes(hashes_path)
    entry = hashes.get(relpath, {})
    return entry.get("data_id")


def set_data_id(hashes_path: str, relpath: str, data_id: str) -> None:
    """Record the Cognee data_id for *relpath*."""
    hashes = load_hashes(hashes_path)
    entry = hashes.setdefault(relpath, {})
    entry["data_id"] = data_id
    save_hashes(hashes_path, hashes)
