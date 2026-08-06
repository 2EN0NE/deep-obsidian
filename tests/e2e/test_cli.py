"""End-to-end CLI tests using Click's CliRunner.

Tests the CLI surface — argument parsing, output format, exit codes,
and basic command workflows.  These do NOT require a real LLM.
"""

from __future__ import annotations

import json
import sys
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
        assert "specify target" in result.output.lower()

    def test_forget_all_and_targets_mutex(self, tmp_path: Path, runner: CliRunner) -> None:
        """forget --all with targets is rejected."""
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="mutex-cli")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["forget", "a.md", "--all"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "both targets and --all" in result.output.lower()

    def test_service_status_no_init(self, tmp_path: Path, runner: CliRunner) -> None:
        """service commands on un-initialized dirs give clear errors."""
        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["service", "status"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "not in a deep-obsidian project" in result.output.lower()


class TestForgetInteractiveConfirmation:
    """forget's ``[y/N]`` prompts (--all, and multi-file) were never fed
    input via CliRunner — every existing forget test uses ``--yes`` or
    hits an error path before reaching the prompt, so neither branch of
    the interactive confirmation (accept/cancel) was exercised.
    """

    def test_forget_all_cancelled_on_n_leaves_data_untouched(
        self, tmp_path: Path, runner: CliRunner, mock_llm
    ) -> None:
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="confirm-cancel")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            runner.invoke(main, ["ingest", str(tmp_path)])
            result = runner.invoke(main, ["forget", "--all"], input="n\n")
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

        from deep_obsidian.ingest._fingerprint import load_hashes

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "a.md" in hashes, "cancelling must not touch hashes.json"

    def test_forget_all_confirmed_on_y_clears_data(
        self, tmp_path: Path, runner: CliRunner, mock_llm
    ) -> None:
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="confirm-accept")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            runner.invoke(main, ["ingest", str(tmp_path)])
            result = runner.invoke(main, ["forget", "--all"], input="y\n")
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        assert "forgotten" in result.output.lower()

        from deep_obsidian.ingest._fingerprint import load_hashes

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert hashes == {}

    def test_forget_multi_file_cancelled_on_n_leaves_data_untouched(
        self, tmp_path: Path, runner: CliRunner, mock_llm
    ) -> None:
        """A directory target matching 2+ indexed files prompts for
        confirmation; answering 'n' must forget nothing."""
        from deep_obsidian.settings import init_project

        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "a.md").write_text("# A")
        (tmp_path / "notes" / "b.md").write_text("# B")
        init_project(tmp_path, name="confirm-multi-cancel")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            runner.invoke(main, ["ingest", str(tmp_path)])
            result = runner.invoke(main, ["forget", "notes"], input="n\n")
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

        from deep_obsidian.ingest._fingerprint import load_hashes

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "notes/a.md" in hashes
        assert "notes/b.md" in hashes

    def test_forget_multi_file_confirmed_on_y_removes_data(
        self, tmp_path: Path, runner: CliRunner, mock_llm
    ) -> None:
        from deep_obsidian.settings import init_project

        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "a.md").write_text("# A")
        (tmp_path / "notes" / "b.md").write_text("# B")
        init_project(tmp_path, name="confirm-multi-accept")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            runner.invoke(main, ["ingest", str(tmp_path)])
            result = runner.invoke(main, ["forget", "notes"], input="y\n")
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0

        from deep_obsidian.ingest._fingerprint import load_hashes

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "hashes.json"))
        assert "notes/a.md" not in hashes
        assert "notes/b.md" not in hashes


class TestIngestInterrupt:
    """Ctrl+C during ingest must exit cleanly, not dump a raw traceback.

    Regression for: KeyboardInterrupt doesn't inherit from Exception, so
    a bare ``except Exception`` around the ingest call let it propagate
    unhandled, producing a scary traceback instead of the conventional
    SIGINT exit code (130) with a clear message.
    """

    def test_keyboard_interrupt_exits_130_with_clear_message(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        from unittest.mock import patch

        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# test")
        init_project(tmp_path, name="interrupt-cli")

        async def _raise_interrupt(*args, **kwargs):
            raise KeyboardInterrupt()

        with patch("deep_obsidian.ingest.ingest", new=_raise_interrupt):
            result = runner.invoke(main, ["ingest", str(tmp_path)])

        assert result.exit_code == 130
        assert "已中断" in result.output
        assert "Traceback" not in result.output


class TestIngestTTYProgressCard:
    """The interactive-terminal progress-card branch of `ingest` (taken
    when ``sys.stderr.isatty()`` is True) is never exercised by any
    CliRunner-based test, because Click's CliRunner always substitutes a
    non-tty stream for stderr. Call the command's callback directly
    (bypassing CliRunner's argument parsing and stream isolation, which
    is already covered elsewhere) with a patched ``isatty`` instead, so
    this branch has at least one regression test.
    """

    def test_success_path_renders_and_finishes_card(
        self, tmp_path: Path, mock_llm, monkeypatch
    ) -> None:
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A\n\nContent.")
        init_project(tmp_path, name="tty-test")

        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

        ingest_callback = main.commands["ingest"].callback
        assert ingest_callback is not None
        # Must not raise — exercises ProgressCard.start_scan/update/
        # start_cognify/finish end to end against a real ingest() run.
        ingest_callback(target=str(tmp_path), full=False, json_output=False)

    def test_keyboard_interrupt_clears_card_and_exits_130(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Regression: the TTY branch's ``finally`` clause calls
        ``card.finish(...)`` when ``_result`` is set, or ``card._clear()``
        when it's still None (interrupted before completion) — only the
        non-tty branch's KeyboardInterrupt handling had a test.
        """
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="tty-interrupt-test")

        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

        async def _raise_interrupt(*args, **kwargs):
            raise KeyboardInterrupt()

        monkeypatch.setattr("deep_obsidian.ingest.ingest", _raise_interrupt)

        ingest_callback = main.commands["ingest"].callback
        assert ingest_callback is not None
        with pytest.raises(SystemExit) as exc_info:
            ingest_callback(target=str(tmp_path), full=False, json_output=False)
        assert exc_info.value.code == 130
