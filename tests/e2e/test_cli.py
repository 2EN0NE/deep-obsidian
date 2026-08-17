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

    def _settings(self, tmp_path: Path) -> dict:
        from deep_obsidian.settings import read_settings

        return read_settings(tmp_path)

    def test_init_creates_settings_json(self, tmp_path: Path, runner: CliRunner) -> None:
        result = runner.invoke(main, ["init", str(tmp_path)])
        assert result.exit_code == 0
        settings_file = tmp_path / ".deep-obsidian" / "settings.jsonc"
        assert settings_file.is_file(), f"Expected {settings_file} to exist"

        data = self._settings(tmp_path)
        assert "deep-obsidian-id" in data
        assert data["name"] == tmp_path.name
        assert "llm" in data
        assert "embedding" in data
        assert "network" in data

    def test_init_with_name(self, tmp_path: Path, runner: CliRunner) -> None:
        result = runner.invoke(main, ["init", str(tmp_path), "--name", "my-project"])
        assert result.exit_code == 0
        data = self._settings(tmp_path)
        assert data["name"] == "my-project"

    def test_init_idempotent(self, tmp_path: Path, runner: CliRunner) -> None:
        """Running init twice does not overwrite settings."""
        runner.invoke(main, ["init", str(tmp_path), "--name", "original"])
        first = self._settings(tmp_path)

        runner.invoke(main, ["init", str(tmp_path), "--name", "override"])
        second = self._settings(tmp_path)

        assert second["name"] == "original"  # idempotent
        assert second["deep-obsidian-id"] == first["deep-obsidian-id"]


class TestErrorMessages:
    """Commands with no config at all (no project, no user) give clear errors."""

    def test_ingest_without_init(self, tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
        empty_home = tmp_path / "nohome"
        empty_home.mkdir()
        monkeypatch.setenv("HOME", str(empty_home))
        (tmp_path / "note.md").write_text("# test")
        result = runner.invoke(main, ["ingest", str(tmp_path)])
        assert result.exit_code != 0
        assert "init" in result.output.lower()

    def test_search_without_init(self, tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
        import os as _os

        empty_home = tmp_path / "nohome"
        empty_home.mkdir()
        monkeypatch.setenv("HOME", str(empty_home))
        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["search", "test"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "init" in result.output.lower()

    def test_search_with_project_but_no_user_level_names_real_cause(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """项目级 .deep-obsidian/ 存在但用户级缺失时，search 报错必须指向
        真实原因（用户级基础层缺失），而不是误导性的"未找到 .deep-obsidian"
        （曾让用户按提示重跑 init 也无济于事）。"""
        import os as _os

        from deep_obsidian.settings import init_project

        empty_home = tmp_path / "nohome"
        empty_home.mkdir()
        monkeypatch.setenv("HOME", str(empty_home))
        init_project(tmp_path, name="proj-only")
        assert (tmp_path / ".deep-obsidian" / "settings.jsonc").is_file()

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["search", "test"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "user-level" in result.output

    def test_forget_without_init(self, tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
        import os as _os

        empty_home = tmp_path / "nohome"
        empty_home.mkdir()
        monkeypatch.setenv("HOME", str(empty_home))
        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["forget", "--yes"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "init" in result.output.lower()

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

    def test_service_status_no_init(self, tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
        """service commands with no config at all give clear errors."""
        import os as _os

        empty_home = tmp_path / "nohome"
        empty_home.mkdir()
        monkeypatch.setenv("HOME", str(empty_home))
        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["service", "status"])
        finally:
            _os.chdir(_cwd)
        assert result.exit_code != 0
        assert "init" in result.output.lower()


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

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json"))
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

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json"))
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

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json"))
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

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json"))
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

        # ingest 现在需要 @click.pass_context 的 ctx——提供假的。
        import click

        ctx = click.Context(main, obj={"config_path": None})
        ingest_callback = main.commands["ingest"].callback
        assert ingest_callback is not None
        # Must not raise — exercises ProgressCard.start_scan/update/
        # start_cognify/finish end to end against a real ingest() run.
        # pass_context 从 context stack 取 ctx（不能显式传，会重复）。
        with ctx:
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
        import click

        ctx = click.Context(main, obj={"config_path": None})
        with ctx, pytest.raises(SystemExit) as exc_info:
            ingest_callback(target=str(tmp_path), full=False, json_output=False)
        assert exc_info.value.code == 130


class TestStatus:
    """Top-level ``deep-obsidian status`` — distinct from ``service status``
    (SPEC-003 / ADR-0009). One-shot snapshot, no --watch.
    """

    def test_idle_json(self, tmp_path: Path, runner: CliRunner) -> None:
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="status-idle")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["status", "--json"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "idle"

    def test_idle_human_readable(self, tmp_path: Path, runner: CliRunner) -> None:
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="status-idle-human")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["status"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        assert "no ingest" in result.output.lower()

    def test_running_json(self, tmp_path: Path, runner: CliRunner) -> None:
        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="status-running")

        import os as _os

        _cwd = _os.getcwd()
        result = None
        try:
            _os.chdir(tmp_path)
            with acquire(tmp_path / ".deep-obsidian", dataset="status-running", total=5) as handle:
                handle.update(phase="adding", current=2, total=5, current_file="b.md")
                result = runner.invoke(main, ["status", "--json"])
        finally:
            _os.chdir(_cwd)

        assert result is not None
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "running"
        assert data["phase"] == "adding"
        assert data["current"] == 2
        assert data["total"] == 5
        assert data["current_file"] == "b.md"

    def test_running_human_readable(self, tmp_path: Path, runner: CliRunner) -> None:
        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="status-running-human")

        import os as _os

        _cwd = _os.getcwd()
        result = None
        try:
            _os.chdir(tmp_path)
            config_dir = tmp_path / ".deep-obsidian"
            with acquire(config_dir, dataset="status-running-human", total=5) as handle:
                handle.update(phase="adding", current=2, total=5, current_file="b.md")
                result = runner.invoke(main, ["status"])
        finally:
            _os.chdir(_cwd)

        assert result is not None
        assert result.exit_code == 0
        assert "adding" in result.output.lower()
        assert "2/5" in result.output
        assert "b.md" in result.output

    def test_stale_json(self, tmp_path: Path, runner: CliRunner) -> None:
        import subprocess

        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="status-stale")

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()

        progress_path = tmp_path / ".deep-obsidian" / "progress.json"
        progress_path.write_text(
            json.dumps(
                {
                    "pid": dead.pid,
                    "dataset": "status-stale",
                    "phase": "cognify",
                    "current": 3,
                    "total": 3,
                    "current_file": "",
                    "started_at": 0,
                }
            )
        )

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["status", "--json"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "stale"
        assert data["phase"] == "cognify"

    def test_stale_human_readable_mentions_crash(self, tmp_path: Path, runner: CliRunner) -> None:
        import subprocess

        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="status-stale-human")

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()

        progress_path = tmp_path / ".deep-obsidian" / "progress.json"
        progress_path.write_text(
            json.dumps(
                {
                    "pid": dead.pid,
                    "dataset": "status-stale-human",
                    "phase": "adding",
                    "current": 1,
                    "total": 4,
                    "current_file": "a.md",
                    "started_at": 0,
                }
            )
        )

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["status"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        assert "1/4" in result.output

    def test_without_init(self, tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
        import os as _os

        empty_home = tmp_path / "nohome"
        empty_home.mkdir()
        monkeypatch.setenv("HOME", str(empty_home))
        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            result = runner.invoke(main, ["status"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code != 0
        assert "init" in result.output.lower()


class TestIngestLockContention:
    """``deep-obsidian ingest`` when another live ingest already holds
    the project's lock (SPEC-003 / ADR-0009, ticket 03) — a friendly
    error, not a raw traceback.
    """

    def test_ingest_reports_friendly_error_when_locked(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="lock-contention")

        with acquire(tmp_path / ".deep-obsidian", dataset="lock-contention", total=1) as handle:
            handle.update(phase="cognify", current=1, total=1, current_file="")
            result = runner.invoke(main, ["ingest", str(tmp_path)])

            assert result.exit_code != 0
            assert "Traceback" not in result.output
            out = result.output.lower()
            assert "lock-contention" in out
            assert "cognify" in out

    def test_ingest_error_includes_how_long_lock_holder_has_been_running(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        import time as _time

        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="lock-elapsed")

        with acquire(tmp_path / ".deep-obsidian", dataset="lock-elapsed", total=1) as handle:
            handle.update(phase="cognify", current=1, total=1, current_file="")
            # Backdate started_at so the friendly message has a
            # non-trivial elapsed duration to report.
            handle._state["started_at"] = _time.time() - 125
            handle.update(phase="cognify", current=1, total=1, current_file="")
            result = runner.invoke(main, ["ingest", str(tmp_path)])

            assert result.exit_code != 0
            assert "02:05" in result.output

    def test_ingest_json_mode_also_friendly_on_lock_contention(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        from deep_obsidian.ingest._progress_state import acquire
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="lock-contention-json")

        config_dir = tmp_path / ".deep-obsidian"
        with acquire(config_dir, dataset="lock-contention-json", total=1) as handle:
            handle.update(phase="adding", current=1, total=1, current_file="a.md")
            result = runner.invoke(main, ["ingest", str(tmp_path), "--json"])

            assert result.exit_code != 0
            assert "Traceback" not in result.output
            assert "lock-contention-json" in result.output


class TestSearch:
    """search 命令输出格式测试。"""

    def test_json_output_includes_elapsed_and_count(
        self, tmp_path: Path, runner: CliRunner, mock_llm
    ) -> None:
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Habits\n\nHabits are automatic.")
        init_project(tmp_path, name="search-json-test")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            runner.invoke(main, ["ingest", str(tmp_path)])
            result = runner.invoke(main, ["search", "habits", "--json"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "results" in data
        assert "elapsed" in data
        assert isinstance(data["elapsed"], (int, float))
        assert data["count"] == len(data["results"])

    def test_human_readable_shows_snippet_and_source(
        self, tmp_path: Path, runner: CliRunner, mock_llm
    ) -> None:
        """人可读输出应包含：编号、片段原文（| 前缀）、出处（@ 前缀）、
        匹配类型（vector/lexical）、耗时和条数汇总行。"""
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text(
            "# Habits\n\nHabits are automatic behaviors triggered by cues."
        )
        init_project(tmp_path, name="search-human-test")

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            runner.invoke(main, ["ingest", str(tmp_path)])
            result = runner.invoke(main, ["search", "habits"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        out = result.output
        # 有编号
        assert "[1]" in out
        # 有片段原文（带 | 缩进）
        assert "    | " in out
        # 有出处（@ 路径）
        assert "    @ " in out
        # 有匹配类型
        has_match_type = "(vector)" in out or "(lexical)" in out
        assert has_match_type, f"Expected (vector) or (lexical) in output: {out}"
        # 有耗时+条数汇总
        assert "搜索耗时 " in out
        assert "共 " in out and " 条结果" in out

    def test_empty_result_shows_no_results(
        self, tmp_path: Path, runner: CliRunner, mock_llm
    ) -> None:
        """无结果时应输出友好提示，不显示耗时汇总。"""
        from unittest.mock import patch

        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Test")
        init_project(tmp_path, name="search-empty-test")

        # mock_llm 的 _fake_recall 始终返回 2 条固定结果，需要在
        # 本测试中 patch recall 返回空列表来验证空结果路径。
        async def _empty_recall(*args, **kwargs):
            return []

        import os as _os

        _cwd = _os.getcwd()
        try:
            _os.chdir(tmp_path)
            runner.invoke(main, ["ingest", str(tmp_path)])
            with patch("deep_obsidian.search._recall_with_retry", new=_empty_recall):
                result = runner.invoke(main, ["search", "nothing"])
        finally:
            _os.chdir(_cwd)

        assert result.exit_code == 0
        assert "No results found." in result.output
        # 无结果时不显示耗时汇总
        assert "搜索耗时" not in result.output


class TestServiceUserLevelGuard:
    """service 是长驻单 vault 进程：用户级配置（~/.deep-obsidian）下不得启动，
    否则守护进程会把 $HOME 当作 vault 全量入库（曾真实发生的回归）。
    """

    def _user_level_home(self, tmp_path, monkeypatch):
        """构造只有用户级配置的 HOME，并把 cwd 移到非项目目录。"""
        from deep_obsidian.settings import init_project

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        init_project(home, name="user", level="user")

        workdir = tmp_path / "elsewhere"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        return home

    def test_service_start_user_level_errors_cleanly(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """项目外（仅用户级配置）service start 报清晰错误，且不 spawn 守护进程。"""
        from unittest.mock import Mock

        self._user_level_home(tmp_path, monkeypatch)

        called = Mock(side_effect=AssertionError("start_service 不应被调用"))
        monkeypatch.setattr("deep_obsidian.service.start_service", called)

        result = runner.invoke(main, ["service", "start"])
        assert result.exit_code != 0
        assert "项目目录" in result.output
        called.assert_not_called()

    def test_service_start_inside_project_still_works(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """项目目录内 service start 不被误拦截（守卫只拦用户级）。"""
        from unittest.mock import Mock

        self._user_level_home(tmp_path, monkeypatch)
        # 在 HOME 下建项目（init 兼建用户级）
        project = tmp_path / "proj"
        project.mkdir()
        runner.invoke(main, ["init", str(project)])
        monkeypatch.chdir(project)

        called = Mock(return_value=12345)
        monkeypatch.setattr("deep_obsidian.service.start_service", called)

        result = runner.invoke(main, ["service", "start"])
        assert result.exit_code == 0, result.output
        called.assert_called_once()

    def test_service_main_rejects_user_level_config_dir(self, tmp_path, monkeypatch) -> None:
        """python -m deep_obsidian.service ~/.deep-obsidian 直接拒绝（不 ingest $HOME）。"""
        import os
        import subprocess
        import sys

        home = self._user_level_home(tmp_path, monkeypatch)
        env = dict(os.environ)
        env.update(
            {
                "HOME": str(home),
                "ENABLE_BACKEND_ACCESS_CONTROL": "false",
                "COGNEE_SKIP_CONNECTION_TEST": "true",
                "TELEMETRY_DISABLED": "1",
            }
        )
        proc = subprocess.run(
            [sys.executable, "-m", "deep_obsidian.service", str(home / ".deep-obsidian")],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
            timeout=120,
        )
        assert proc.returncode != 0
        assert "用户级配置目录" in proc.stderr
