"""Unit tests for deep_obsidian.logging_config.

Regression: setup_logging() has real filesystem side effects (creates
.deep-obsidian/logs/, redirects Cognee's own logs via COGNEE_LOGS_DIR)
and a documented MUST-run-before-any-Cognee-import ordering constraint
(SPEC-002.md), but had zero direct unit test coverage — only an
indirect, weak proxy assertion ("structlog" not in --help output) in
tests/e2e/test_cli.py::test_help_clean.
"""

from __future__ import annotations

import logging

import pytest

from deep_obsidian import logging_config
from deep_obsidian.logging_config import (
    _resolve_root,
    _to_level,
    get_logger,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_logger_global():
    """setup_logging()/get_logger() share a module-level `_logger`
    global — reset it around every test so tests don't leak state into
    each other (e.g. get_logger() succeeding only because an earlier
    test already called setup_logging()).
    """
    logging_config._logger = None
    yield
    logging_config._logger = None


class TestSetupLogging:
    def test_creates_logs_directory(self, tmp_path):
        setup_logging(tmp_path)
        assert (tmp_path / ".deep-obsidian" / "logs").is_dir()

    def test_returns_configured_logger_with_two_handlers(self, tmp_path):
        logger = setup_logging(tmp_path)
        assert logger.name == "deep_obsidian"
        assert len(logger.handlers) == 2

    def test_repeated_calls_do_not_accumulate_handlers(self, tmp_path):
        """setup_logging() clears handlers on each call — calling it
        twice (e.g. once for --debug detection, once for real) must not
        double up file/console output.
        """
        setup_logging(tmp_path)
        setup_logging(tmp_path)
        assert len(logging_config.get_logger().handlers) == 2

    def test_debug_flag_sets_console_handler_to_debug(self, tmp_path):
        logger = setup_logging(tmp_path, debug=True)
        _file_handler, console_handler = logger.handlers
        assert console_handler.level == logging.DEBUG

    def test_sets_cognee_logs_dir_env_var(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COGNEE_LOGS_DIR", raising=False)
        setup_logging(tmp_path)
        import os

        assert os.environ["COGNEE_LOGS_DIR"] == str(tmp_path / ".deep-obsidian" / "logs" / "cognee")

    def test_does_not_override_existing_cognee_logs_dir(self, tmp_path, monkeypatch):
        """Regression: setup_logging() must use setdefault, not a bare
        assignment — a user-provided COGNEE_LOGS_DIR must win.
        """
        monkeypatch.setenv("COGNEE_LOGS_DIR", "/custom/log/path")
        setup_logging(tmp_path)
        import os

        assert os.environ["COGNEE_LOGS_DIR"] == "/custom/log/path"

    def test_file_handler_writes_to_deep_obsidian_log(self, tmp_path):
        logger = setup_logging(tmp_path)
        logger.error("boom")
        for h in logger.handlers:
            h.flush()
        log_file = tmp_path / ".deep-obsidian" / "logs" / "deep-obsidian.log"
        assert log_file.is_file()
        assert "boom" in log_file.read_text()


class TestGetLogger:
    def test_raises_before_setup(self):
        with pytest.raises(RuntimeError, match="not configured"):
            get_logger()

    def test_returns_same_logger_after_setup(self, tmp_path):
        configured = setup_logging(tmp_path)
        assert get_logger() is configured


class TestResolveRoot:
    def test_explicit_project_root_used_as_is(self, tmp_path):
        assert _resolve_root(tmp_path) == tmp_path

    def test_falls_back_to_find_project_root_when_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(logging_config, "find_project_root", lambda _cwd: tmp_path)
        assert _resolve_root(None) == tmp_path

    def test_falls_back_to_home_silently_when_no_project_found(self, monkeypatch, capsys):
        monkeypatch.setattr(logging_config, "find_project_root", lambda _cwd: None)
        from pathlib import Path

        result = _resolve_root(None)
        assert result == Path.home()
        captured = capsys.readouterr()
        assert captured.err == ""  # no longer emits a warning


class TestToLevel:
    def test_known_levels(self):
        assert _to_level("DEBUG") == logging.DEBUG
        assert _to_level("info") == logging.INFO
        assert _to_level("Warning") == logging.WARNING
        assert _to_level("ERROR") == logging.ERROR
        assert _to_level("CRITICAL") == logging.CRITICAL

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError, match="Invalid log level"):
            _to_level("NOT_A_LEVEL")


class TestLevelsFromSettings:
    def test_file_level_read_from_settings(self, tmp_path):
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="log-level-test")
        settings_path = tmp_path / ".deep-obsidian" / "settings.json"
        import json

        settings = json.loads(settings_path.read_text())
        settings["logging"] = {"file_level": "DEBUG", "console_level": "ERROR"}
        settings_path.write_text(json.dumps(settings))

        logger = setup_logging(tmp_path)
        file_handler, console_handler = logger.handlers
        assert file_handler.level == logging.DEBUG
        assert console_handler.level == logging.ERROR

    def test_missing_settings_falls_back_to_defaults(self, tmp_path):
        """No .deep-obsidian/ at all (uninitialized project) must not
        crash setup_logging() — file/console levels fall back to
        INFO/WARNING.
        """
        logger = setup_logging(tmp_path)
        file_handler, console_handler = logger.handlers
        assert file_handler.level == logging.INFO
        assert console_handler.level == logging.WARNING
