"""Settings management — .deep-obsidian/settings.json read/write."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

SETTINGS_DIR = ".deep-obsidian"
SETTINGS_FILE = "settings.json"
CLI_VERSION = "0.1.0"


def find_project_root(path: str | Path) -> Path | None:
    """Walk up from path to find a directory containing .deep-obsidian/.

    A .deep-obsidian/ directory alone is not enough — Cognee may create
    one as a log fallback in e.g. $HOME/.deep-obsidian/.  The directory
    must also contain settings.json, which is created by ``init``.

    Returns the project root, or None if no project is found.
    """
    current = Path(path).resolve()
    if not current.exists():
        return None

    for parent in [current, *current.parents]:
        settings_dir = parent / SETTINGS_DIR
        if settings_dir.is_dir() and (settings_dir / SETTINGS_FILE).is_file():
            return parent
    return None


def read_settings(project_root: str | Path) -> dict:
    """Read and parse the settings.json in the project root."""
    settings_path = Path(project_root) / SETTINGS_DIR / SETTINGS_FILE
    if not settings_path.is_file():
        raise FileNotFoundError(
            f"Project settings not found at {settings_path}. Run 'deep-obsidian init' first."
        )
    return json.loads(settings_path.read_text(encoding="utf-8"))


def write_settings(project_root: str | Path, data: dict) -> None:
    """Write settings dict to the project's settings.json."""
    settings_dir = Path(project_root) / SETTINGS_DIR
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path = settings_dir / SETTINGS_FILE
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def init_project(path: str | Path, name: str | None = None, *, force: bool = False) -> dict:
    """Initialize a new project at path.

    Creates .deep-obsidian/settings.json with default values.
    If settings already exist, returns them without overwriting
    unless ``force=True``.

    When ``force=True``, removes EVERYTHING that could carry stale
    state from a previous run — .deep-obsidian/, .cognee/, and even
    Cognee's log-fallback directory in $HOME — before re-creating
    the project from scratch.  This is the "factory reset" path.
    """
    import shutil

    root = Path(path).resolve()
    settings_dir = root / SETTINGS_DIR
    settings_path = settings_dir / SETTINGS_FILE

    if force:
        for _dir, _label in [
            (settings_dir, "vault .deep-obsidian/"),
            (root / ".cognee", "vault .cognee/"),
            (Path.home() / SETTINGS_DIR, "$HOME/.deep-obsidian/"),
        ]:
            try:
                if _dir.exists():
                    shutil.rmtree(_dir)
            except OSError:
                pass  # locked / permissions — continue, not fatal
    elif settings_path.is_file():
        return json.loads(settings_path.read_text(encoding="utf-8"))

    now = datetime.now(UTC).isoformat()
    data = {
        "deep-obsidian-id": str(uuid.uuid4()),
        "name": name or root.name,
        "created_at": now,
        "last_used_at": now,
        "cli_version": CLI_VERSION,
        "backend": {
            "type": "cognee",
            "cognee": {
                "llm_provider": "openai",
                "llm_model": "deepseek-chat",
                "llm_endpoint": "",
                "embedding_model": "BAAI/bge-small-en-v1.5",
            },
        },
        "logging": {
            "file_level": "INFO",
            "console_level": "WARNING",
        },
    }
    write_settings(root, data)
    return data
