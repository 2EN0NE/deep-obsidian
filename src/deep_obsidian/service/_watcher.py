"""File watcher — watchfiles integration with dynamic debounce and polling."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from watchfiles import Change, awatch

from deep_obsidian.ingest._fingerprint import file_hash, load_hashes
from deep_obsidian.ingest._scanner import scan_vault

# Debounce cooldown: after processing an event for a file, ignore new events
# for this many seconds. Prevents duplicate processing from rapid saves.
_DEBOUNCE_COOLDOWN = 2.0

# Supported watchfiles change types
_FILE_CHANGE_TYPES = {Change.added, Change.modified, Change.deleted}


async def watch(
    vault: Path,
    project_root: Path,
    shutdown_event: asyncio.Event,
    on_event: Callable[[str, str], Awaitable[None]],
) -> None:
    """Watch a vault directory for .md file changes.

    Combines watchfiles events (primary) with periodic polling (fallback).
    Dynamic debounce prevents duplicate processing of rapid saves.

    *on_event* is called with ``(relpath: str, event_type: str)`` where
    event_type is one of ``"created"``, ``"modified"``, ``"deleted"``.
    """
    hashes_path = project_root / ".deep-obsidian" / "hashes.json"
    vault_str = str(vault)

    # Track last-processed time per file for debounce
    last_processed: dict[str, float] = {}
    # Track files seen in current batch (dedup within a batch)
    _seen: set[str] = set()

    async def _handle(path_str: str, event_type: str) -> None:
        """Debounce and dispatch a single file event."""
        now = time.monotonic()
        rel = _relative_path(path_str, vault)
        if rel is None:
            return
        if not rel.endswith(".md"):
            return
        if _is_skip_dir(rel):
            return

        # Debounce check
        last = last_processed.get(rel, 0)
        if now - last < _DEBOUNCE_COOLDOWN:
            return

        # Hash-based dedup — only for non-deletion events.
        # file_hash() is a TOCTOU read: the file may be deleted between
        # the awatch event and this call (editor temp file cleanup, etc.).
        # Treat that as "the file went away" rather than crashing.
        stored = load_hashes(str(hashes_path))
        stored_entry = stored.get(rel, {})

        actual_type = event_type
        if event_type == "modified":
            try:
                current_hash = file_hash(str(vault / rel))
            except FileNotFoundError:
                return  # deleted between event and hash — ignore
            if stored_entry.get("hash") == current_hash:
                return  # content didn't actually change
        elif event_type == "created":
            try:
                current_hash = file_hash(str(vault / rel))
            except FileNotFoundError:
                return  # created then immediately deleted — ignore
            if rel in stored:
                # Already tracked — treat as modified
                if stored_entry.get("hash") == current_hash:
                    return
                actual_type = "modified"

        last_processed[rel] = now
        await on_event(rel, actual_type)

    # Polling fallback — runs every 30s
    async def _poll_loop() -> None:
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=30.0)
                return
            except TimeoutError:
                pass

            stored = load_hashes(str(hashes_path))
            current = {str(f) for f in scan_vault(vault_str)}
            stored_set = set(stored.keys())

            for rel in current - stored_set:
                if rel not in last_processed or time.monotonic() - last_processed.get(rel, 0) >= 5:
                    try:
                        await _handle(str(vault / rel), "created")
                    except FileNotFoundError:
                        pass  # raced with deletion between scan and handle
                    except Exception:
                        print(
                            f"[deep-obsidian] [warn] poll created failed: {rel}",
                            file=sys.stderr,
                        )
            for rel in stored_set - current:
                try:
                    await _handle(str(vault / rel), "deleted")
                except FileNotFoundError:
                    pass  # already gone
                except Exception:
                    print(
                        f"[deep-obsidian] [warn] poll deleted failed: {rel}",
                        file=sys.stderr,
                    )
            for rel in current & stored_set:
                try:
                    current_hash = file_hash(str(vault / rel))
                except FileNotFoundError:
                    continue  # raced with deletion between scan and hash
                if stored[rel].get("hash") != current_hash:
                    if (
                        rel not in last_processed
                        or time.monotonic() - last_processed.get(rel, 0) >= 5
                    ):
                        try:
                            await _handle(str(vault / rel), "modified")
                        except FileNotFoundError:
                            pass  # raced with deletion
                        except Exception:
                            print(
                                f"[deep-obsidian] [warn] poll modified failed: {rel}",
                                file=sys.stderr,
                            )

    # Start polling in background
    poll_task = asyncio.create_task(_poll_loop())

    try:
        async for changes in awatch(vault_str, recursive=True, stop_event=shutdown_event):
            _seen.clear()
            for change_type, path_str in changes:
                if change_type not in _FILE_CHANGE_TYPES:
                    continue
                path = Path(path_str)
                if path.name.startswith("."):
                    continue

                rel = _relative_path(path_str, vault)
                if rel is None:
                    continue
                if not rel.endswith(".md"):
                    continue
                if _is_skip_dir(rel):
                    continue
                if rel in _seen:
                    continue
                _seen.add(rel)

                if change_type == Change.deleted:
                    event_type = "deleted"
                elif change_type == Change.added:
                    event_type = "created"
                else:
                    event_type = "modified"

                await _handle(str(vault / rel), event_type)
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


def _relative_path(abs_path: str, vault: Path) -> str | None:
    """Convert absolute path to vault-relative, or None if outside vault."""
    try:
        p = Path(abs_path).resolve()
        v = vault.resolve()
        return str(p.relative_to(v))
    except ValueError:
        return None


def _is_skip_dir(rel: str) -> bool:
    """Check if the relative path is in a directory that should be skipped."""
    skip = {
        ".obsidian",
        ".trash",
        ".git",
        ".cognee",
        "attachments",
        "node_modules",
        "__pycache__",
    }
    parts = Path(rel).parts
    return any(p in skip or p.startswith(".") for p in parts[:-1])
