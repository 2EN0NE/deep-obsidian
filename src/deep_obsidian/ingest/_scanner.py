"""Vault file scanner — walk directories, filter markdown files."""

import os
from pathlib import Path

# Directories always skipped during scan
_SKIP_DIRS = {
    ".obsidian",
    ".trash",
    ".git",
    ".cognee",
    ".cognee-obsidian",
    "attachments",
    "node_modules",
    "__pycache__",
}


def scan_vault(vault_path: str) -> list[Path]:
    """Recursively collect all .md files in a vault directory.

    Skips hidden directories (starting with .) and known cache / data
    directories (including internal storage like .cognee-obsidian).

    Returns a sorted list of Path objects relative to vault_path.
    """
    root = Path(vault_path).resolve()

    if not root.exists():
        raise FileNotFoundError(f"Vault path does not exist: {vault_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"Vault path is not a directory: {vault_path}")

    files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]

        for fname in filenames:
            if fname.endswith(".md"):
                fpath = Path(dirpath) / fname
                files.append(fpath.relative_to(root))

    return sorted(files)
