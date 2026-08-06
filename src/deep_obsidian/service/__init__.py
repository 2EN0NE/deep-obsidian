"""Service daemon — background file watcher and incremental sync."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from deep_obsidian.ingest import ingest
from deep_obsidian.service._pidfile import (
    is_process_alive,
    pidfile_path,
    read_pid,
    remove_pid,
    write_pid,
)
from deep_obsidian.service._watcher import watch
from deep_obsidian.settings import read_settings


def _find_vault(project_root: Path) -> Path:
    """Derive the vault path from the project root.

    The vault is assumed to be the project root itself (the common case
    where .deep-obsidian/ lives inside the Obsidian vault).
    """
    return project_root


async def run_service(project_root: Path) -> None:
    """Run the service event loop (blocking).

    Sets up signal handlers for graceful shutdown, then enters the
    main watcher loop.
    """
    vault = _find_vault(project_root)
    _settings = read_settings(project_root)
    dataset_name: str = _settings["name"]

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _on_sigterm() -> None:
        shutdown_event.set()

    try:
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
        loop.add_signal_handler(signal.SIGINT, _on_sigterm)
    except NotImplementedError:
        # add_signal_handler is not implemented on Windows' default
        # asyncio event loop (ProactorEventLoop) — ADR-0004 picked
        # watchfiles specifically for Windows support, so this must not
        # crash the service on startup there. Signal-based graceful
        # shutdown (SIGTERM from `service stop`) is unavailable in that
        # case; stop_service() falls back to SIGKILL after its 10s
        # grace-period wait.
        _log(
            "warning",
            "Signal handlers unavailable on this platform "
            "(likely Windows) — graceful SIGTERM shutdown is disabled; "
            "the process will be force-killed on 'service stop' instead.",
        )

    write_pid(project_root, os.getpid())
    ingest_lock = asyncio.Lock()

    try:
        # Initial full scan on startup
        result = await ingest(str(vault), dataset=dataset_name)
        _log("info", f"Initial scan: {_format_stats(result)}")

        # File event → ingest handler
        async def _on_file_event(rel: str, event_type: str) -> None:
            async with ingest_lock:
                result = await ingest(str(vault), dataset=dataset_name)
            total = result.get("added", 0) + result.get("modified", 0) + result.get("deleted", 0)
            if total > 0:
                _log("info", f"{event_type} {rel}: {_format_stats(result)}")

        # Main watcher loop (with built-in 30s polling fallback)
        _log("info", f"Watching {vault} for changes...")
        await watch(vault, project_root, shutdown_event, _on_file_event)

    finally:
        _log("info", "Service shutting down...")
        remove_pid(project_root)


def start_service(project_root: Path) -> int:
    """Start the service as a daemon process. Returns the PID."""
    import subprocess

    pf = pidfile_path(project_root)
    pf.parent.mkdir(parents=True, exist_ok=True)

    # Check for existing (possibly stale) PID file
    existing_pid = read_pid(project_root)
    if existing_pid is not None:
        if is_process_alive(existing_pid):
            raise RuntimeError(f"Service already running (PID: {existing_pid})")
        # Stale PID — clean up
        remove_pid(project_root)

    # Exclusive create to guard against concurrent starts
    try:
        fd = os.open(str(pf), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        # Race: another process created the file between our read and open
        pid = read_pid(project_root)
        if pid is not None and is_process_alive(pid):
            raise RuntimeError(f"Service already running (PID: {pid})")
        # Stale — remove and retry once
        remove_pid(project_root)
        fd = os.open(str(pf), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)

    # Prepare environment for the child process
    child_env = os.environ.copy()
    child_env.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
    child_env.setdefault("COGNEE_SKIP_CONNECTION_TEST", "true")

    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "deep_obsidian.service", str(project_root)],
            env=child_env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.write(fd, str(child.pid).encode())
        os.close(fd)
        return child.pid
    except Exception:
        os.close(fd)
        try:
            os.unlink(str(pf))
        except FileNotFoundError:
            pass
        raise


def stop_service(project_root: Path) -> bool:
    """Stop a running service. Returns True if it was running."""
    pid = read_pid(project_root)
    if pid is None:
        return False
    if not is_process_alive(pid):
        remove_pid(project_root)
        return False

    os.kill(pid, signal.SIGTERM)
    # Wait up to 10s for graceful shutdown
    import time

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            remove_pid(project_root)
            return True
        time.sleep(0.1)

    # Force kill
    os.kill(pid, signal.SIGKILL)
    remove_pid(project_root)
    return True


def service_status(project_root: Path) -> dict:
    """Return the current service status."""
    pid = read_pid(project_root)
    if pid is None:
        return {"status": "stopped", "pid": None}
    if is_process_alive(pid):
        return {"status": "running", "pid": pid}
    return {"status": "stale_pid", "pid": pid, "detail": "PID file exists but process is dead"}


def _format_stats(result: dict) -> str:
    parts = []
    for key in ("added", "modified", "deleted", "unchanged", "failed"):
        if result.get(key):
            parts.append(f"{key}={result[key]}")
    return ", ".join(parts) if parts else "no changes"


def _log(level: str, msg: str) -> None:
    """Minimal logger until structured logging is wired in T7."""
    print(f"[deep-obsidian] [{level}] {msg}", file=sys.stderr, flush=True)
