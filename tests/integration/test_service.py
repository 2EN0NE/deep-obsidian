"""Integration tests for service daemon lifecycle — real subprocess."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.integration
class TestServiceSubprocess:
    """Start/stop the service daemon as a real child process."""

    def test_service_starts_and_stops(self, tmp_path: Path) -> None:
        """Service subprocess: vault has no .md files → ingest is a no-op.
        The daemon starts, writes a PID file, and exits cleanly on SIGTERM.
        """
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="svc-sub-test")
        # No .md files → initial ingest returns zero counts, no Cognee needed

        # Inherit parent env + disable Cognee access control
        child_env = os.environ.copy()
        child_env["ENABLE_BACKEND_ACCESS_CONTROL"] = "false"
        child_env["COGNEE_SKIP_CONNECTION_TEST"] = "true"

        child = subprocess.Popen(
            [sys.executable, "-m", "deep_obsidian.service", str(tmp_path)],
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        pidfile = tmp_path / ".deep-obsidian" / "service.pid"

        try:
            # Wait for PID file to appear (daemon startup)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not pidfile.exists():
                if child.poll() is not None:
                    pytest.fail(f"Service exited early with code {child.returncode}")
                time.sleep(0.2)
            assert pidfile.exists(), "PID file was not created"

            # PID file should contain the child's PID
            assert pidfile.read_text().strip() == str(child.pid)

            # SIGTERM → graceful shutdown → PID file removed
            child.send_signal(signal.SIGTERM)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and child.poll() is None:
                time.sleep(0.2)
            assert child.poll() is not None, "Service did not exit after SIGTERM"
            assert not pidfile.exists(), "PID file not cleaned up on shutdown"
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            if pidfile.exists():
                pidfile.unlink()


@pytest.mark.integration
class TestServiceLifecycleAPI:
    """Exercise start_service()/stop_service() themselves, not a manually
    replicated Popen+signal sequence.

    Regression: the module-level daemon (spawned via
    ``python -m deep_obsidian.service``) was covered by
    ``test_service_starts_and_stops`` above via a hand-rolled
    subprocess.Popen + send_signal sequence, but the actual
    ``start_service()``/``stop_service()`` Python functions that the CLI
    calls — including their stale-PID detection, the O_CREAT|O_EXCL
    concurrent-start guard, and stop_service's SIGTERM-then-SIGKILL
    fallback — were never exercised by any test.
    """

    def test_start_stop_roundtrip(self, tmp_path: Path) -> None:
        from deep_obsidian.service import service_status, start_service, stop_service
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="svc-api-test")

        pid = start_service(tmp_path)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if service_status(tmp_path)["status"] == "running":
                    break
                time.sleep(0.2)
            assert service_status(tmp_path) == {"status": "running", "pid": pid}

            stopped = stop_service(tmp_path)
            assert stopped
            assert service_status(tmp_path)["status"] == "stopped"
        finally:
            # Best-effort cleanup if the assertions above failed midway.
            st = service_status(tmp_path)
            if st["status"] in ("running", "stale_pid") and st["pid"]:
                try:
                    os.kill(st["pid"], signal.SIGKILL)
                except OSError:
                    pass

    def test_concurrent_start_raises_already_running(self, tmp_path: Path) -> None:
        """A second start_service() while one is already running must
        raise, not spawn a second daemon competing over the same vault.
        """
        from deep_obsidian.service import start_service, stop_service
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="svc-race-test")

        start_service(tmp_path)
        try:
            with pytest.raises(RuntimeError, match="already running"):
                start_service(tmp_path)
        finally:
            stop_service(tmp_path)

    def test_start_after_stale_pid_cleans_up_and_restarts(self, tmp_path: Path) -> None:
        """start_service() must recover from a stale PID file left behind
        by an unclean shutdown (e.g. the machine losing power, or the
        daemon being SIGKILLed by something other than stop_service()).

        Regression: only the 'process is still alive -> raise' branch of
        start_service()'s PID-file check was ever exercised by a test;
        the 'process is dead -> clean up and start fresh' branch (the
        actual crash-recovery path) had none.
        """
        from deep_obsidian.service import service_status, start_service, stop_service
        from deep_obsidian.service._pidfile import pidfile_path, write_pid
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="svc-stale-pid-test")

        # Produce a real, definitely-dead PID: spawn a subprocess that
        # exits immediately and wait for it, then reuse its now-reaped PID.
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait(timeout=5)
        write_pid(tmp_path, dead.pid)

        pid = start_service(tmp_path)
        try:
            # A fresh PID file was written by the newly-started daemon —
            # not left pointing at the stale, dead PID.
            assert pidfile_path(tmp_path).read_text().strip() == str(pid)

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if service_status(tmp_path)["status"] == "running":
                    break
                time.sleep(0.2)
            assert service_status(tmp_path) == {"status": "running", "pid": pid}
        finally:
            stop_service(tmp_path)
