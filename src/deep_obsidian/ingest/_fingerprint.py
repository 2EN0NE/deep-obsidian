"""File fingerprinting for incremental ingestion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_hash(filepath: str | Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    return hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:16]


def load_hashes(hashes_path: str) -> dict[str, str]:
    """Load the stored file→hash mapping."""
    try:
        return json.loads(Path(hashes_path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_hashes(hashes_path: str, mapping: dict[str, str]) -> None:
    """Persist file→hash mapping."""
    Path(hashes_path).parent.mkdir(parents=True, exist_ok=True)
    Path(hashes_path).write_text(json.dumps(mapping, indent=2))
