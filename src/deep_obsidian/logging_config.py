"""Logging configuration for deep-obsidian.

Sets up Python's :mod:`logging` for the deep-obsidian middleware and
redirects Cognee's file logs so everything lives under
``.deep-obsidian/logs/``.

Call :func:`setup_logging` once, before any Cognee module is imported.
"""

from __future__ import annotations

import logging
import os as _os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from deep_obsidian.settings import SETTINGS_DIR, find_project_root, read_settings

LOG_SUBDIR = "logs"
COGNEE_LOG_SUBDIR = "cognee"
DEEP_OBSIDIAN_LOG = "deep-obsidian.log"

_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3

_logger: logging.Logger | None = None


def setup_logging(
    project_root: Path | None = None,
    *,
    debug: bool = False,
) -> logging.Logger:
    """Configure deep-obsidian logging.

    Must be called **before** any Cognee import so that
    ``COGNEE_LOGS_DIR`` takes effect when Cognee initialises its
    structlog pipeline.

    Args:
        project_root: Project root (containing ``.deep-obsidian/``).
            If *None*, ``find_project_root(Path.cwd())`` is used; if
            that also returns *None* the global fallback
            ``~/.deep-obsidian/logs/`` is used and a warning is
            printed.
        debug: When *True*, the console handler is set to ``DEBUG``
            instead of ``WARNING``.
    """
    global _logger

    resolved = _resolve_root(project_root)
    logs_dir = resolved / SETTINGS_DIR / LOG_SUBDIR
    logs_dir.mkdir(parents=True, exist_ok=True)

    # ── Deep-obsidian logger ──────────────────────────────
    _logger = logging.getLogger("deep_obsidian")
    _logger.setLevel(logging.DEBUG)  # handlers control actual levels
    _logger.handlers.clear()
    _logger.propagate = False

    # File handler
    file_path = logs_dir / DEEP_OBSIDIAN_LOG
    fh = RotatingFileHandler(
        str(file_path),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(_read_file_level(resolved))
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    _logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.DEBUG if debug else _read_console_level(resolved))
    ch.setFormatter(logging.Formatter("[%(levelname)-7s] %(message)s"))
    _logger.addHandler(ch)

    # ── Redirect Cognee logs ──────────────────────────────
    cognee_logs = logs_dir / COGNEE_LOG_SUBDIR
    # Only set if not already overridden by the user
    _os.environ.setdefault("COGNEE_LOGS_DIR", str(cognee_logs))

    _logger.debug("Logging initialised — logs: %s", logs_dir)
    _logger.debug("Cognee logs redirected to: %s", cognee_logs)

    return _logger


def get_logger() -> logging.Logger:
    """Return the configured deep-obsidian logger.

    Raises :class:`RuntimeError` if :func:`setup_logging` has not been
    called yet.
    """
    if _logger is None:
        raise RuntimeError("Logging not configured — call setup_logging() first")
    return _logger


# ── helpers ────────────────────────────────────────────────


def _resolve_root(project_root: Path | None) -> Path:
    if project_root is not None:
        return project_root
    found = find_project_root(Path.cwd())
    if found is not None:
        return found
    fallback = Path.home()
    print(
        f"[WARNING] No .deep-obsidian/ directory found. "
        f"Run 'deep-obsidian init' first. "
        f"Logs will be written to {fallback / SETTINGS_DIR / LOG_SUBDIR}",
        file=sys.stderr,
    )
    return fallback


def _read_file_level(project_root: Path) -> int:
    try:
        settings = read_settings(project_root)
        level = settings.get("logging", {}).get("file_level", "INFO")
    except (FileNotFoundError, KeyError):
        level = "INFO"
    return _to_level(level)


def _read_console_level(project_root: Path) -> int:
    try:
        settings = read_settings(project_root)
        level = settings.get("logging", {}).get("console_level", "WARNING")
    except (FileNotFoundError, KeyError):
        level = "WARNING"
    return _to_level(level)


def _to_level(name: str) -> int:
    level = getattr(logging, name.upper(), None)
    if level is None:
        raise ValueError(
            f"Invalid log level: {name!r}. Expected one of DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )
    return level
