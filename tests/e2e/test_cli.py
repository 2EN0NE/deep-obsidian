"""End-to-end CLI tests using Click's CliRunner.

Tests the CLI surface — argument parsing, output format, exit codes,
and basic command workflows.  These do NOT require a real LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from deep_obsidian.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestHelpAndVersion:
    """Fast-path commands that should never import Cognee."""

    def test_help_clean(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        # No Cognee noise in output
        assert "structlog" not in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output


class TestInit:
    """init command creates a valid project skeleton."""

    def test_init_creates_settings_json(self, tmp_path: Path, runner: CliRunner) -> None:
        result = runner.invoke(main, ["init", str(tmp_path)])
        assert result.exit_code == 0
        settings = tmp_path / ".deep-obsidian" / "settings.json"
        assert settings.is_file(), f"Expected {settings} to exist"

        data = json.loads(settings.read_text())
        assert "deep-obsidian-id" in data
        assert data["name"] == tmp_path.name
        assert "backend" in data
        assert "logging" in data
        assert data["logging"]["file_level"] == "INFO"

    def test_init_with_name(self, tmp_path: Path, runner: CliRunner) -> None:
        result = runner.invoke(main, ["init", str(tmp_path), "--name", "my-project"])
        assert result.exit_code == 0
        settings = tmp_path / ".deep-obsidian" / "settings.json"
        data = json.loads(settings.read_text())
        assert data["name"] == "my-project"

    def test_init_idempotent(self, tmp_path: Path, runner: CliRunner) -> None:
        """Running init twice does not overwrite settings."""
        runner.invoke(main, ["init", str(tmp_path), "--name", "original"])
        first = json.loads((tmp_path / ".deep-obsidian" / "settings.json").read_text())

        runner.invoke(main, ["init", str(tmp_path), "--name", "override"])
        second = json.loads((tmp_path / ".deep-obsidian" / "settings.json").read_text())

        assert second["name"] == "original"  # idempotent
        assert second["deep-obsidian-id"] == first["deep-obsidian-id"]


class TestErrorMessages:
    """Commands on un-initialized directories give clear errors."""

    def test_ingest_without_init(self, tmp_path: Path, runner: CliRunner) -> None:
        (tmp_path / "note.md").write_text("# test")
        result = runner.invoke(main, ["ingest", str(tmp_path)])
        assert result.exit_code != 0
        assert "init" in result.output.lower()

    def test_search_without_init(self, tmp_path: Path, runner: CliRunner) -> None:
        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["search", "test"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "init" in result.output.lower()

    def test_forget_without_init(self, tmp_path: Path, runner: CliRunner) -> None:
        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["forget", "--yes"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "init" in result.output.lower()
