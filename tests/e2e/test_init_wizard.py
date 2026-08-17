"""Tests for the init command — interactive config wizard (ADR-0013).

Covers: mixed mode (PATH arg vs interactive prompt), non-TTY fallback,
existing-config prefilling, and comment-preserving writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from deep_obsidian.cli import main
from deep_obsidian.settings import read_settings


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _settings(tmp_path: Path) -> dict:
    return read_settings(tmp_path)


class TestInitNonInteractive:
    """无 TTY（非交互）时 init 走 fallback，不卡在输入。"""

    def test_init_with_path_creates_jsonc(self, tmp_path: Path, runner: CliRunner) -> None:
        result = runner.invoke(main, ["init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".deep-obsidian" / "settings.jsonc").is_file()
        data = _settings(tmp_path)
        assert data["name"] == tmp_path.name
        assert "llm" in data and "embedding" in data and "network" in data

    def test_init_with_name(self, tmp_path: Path, runner: CliRunner) -> None:
        result = runner.invoke(main, ["init", str(tmp_path), "--name", "my-vault"])
        assert result.exit_code == 0, result.output
        assert _settings(tmp_path)["name"] == "my-vault"

    def test_init_idempotent(self, tmp_path: Path, runner: CliRunner) -> None:
        runner.invoke(main, ["init", str(tmp_path), "--name", "original"])
        first = _settings(tmp_path)
        runner.invoke(main, ["init", str(tmp_path), "--name", "override"])
        second = _settings(tmp_path)
        assert second["name"] == "original"
        assert second["deep-obsidian-id"] == first["deep-obsidian-id"]

    def test_init_non_tty_falls_back_to_defaults(self, tmp_path: Path, runner: CliRunner) -> None:
        """非 TTY 下 init 不交互，直接用默认配置。"""
        result = runner.invoke(main, ["init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        data = _settings(tmp_path)
        assert data["llm"]["provider"] == "openai"

    def test_init_missing_path_without_tty_errors(self, tmp_path: Path, runner: CliRunner) -> None:
        """非 TTY 且没给 PATH——无法交互询问，应给出清晰错误。"""
        result = runner.invoke(main, ["init"], input="\n")
        assert result.exit_code != 0
        assert "path" in result.output.lower() or "PATH" in result.output

    def test_init_warns_about_legacy_config_files(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """旧 .env / settings.json 存在时，init 给出迁移警告（ADR-0011）。"""
        (tmp_path / ".env").write_text("LLM_API_KEY=old")
        (tmp_path / ".deep-obsidian").mkdir()
        (tmp_path / ".deep-obsidian" / "settings.json").write_text('{"name":"old"}')

        result = runner.invoke(main, ["init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert ".env" in result.output
        assert "settings.json" in result.output
        assert "settings.jsonc" in result.output


class TestInitInteractive:
    """交互式引导（DEEP_OBSIDIAN_INTERACTIVE=1 模拟 TTY）。"""

    def _interactive(self, monkeypatch) -> None:
        monkeypatch.setenv("DEEP_OBSIDIAN_INTERACTIVE", "1")

    def test_interactive_prompts_for_llm_provider(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """交互模式询问 LLM provider，输入值写入 jsonc。"""
        self._interactive(monkeypatch)
        result = runner.invoke(
            main,
            ["init", str(tmp_path)],
            input=(
                "1\n"  # 层级：项目级（默认）
                "y\n"  # 兼建用户级共享配置
                "2\n"  # provider 选择 2 = custom
                "openai/deepseek-v4-pro\n"  # model
                "sk-test-123\n"  # api_key
                "http://localhost:8317/v1\n"  # endpoint
                "\n\n\n"  # embedding: provider/model/dims 回车
                "\n"  # network: hf_endpoint 回车
                "\n"  # network: hf_hub_offline 回车（默认不启用）
            ),
        )
        assert result.exit_code == 0, result.output
        data = _settings(tmp_path)
        assert data["llm"]["provider"] == "custom"
        assert data["llm"]["model"] == "openai/deepseek-v4-pro"
        assert data["llm"]["api_key"] == "sk-test-123"
        assert data["llm"]["endpoint"] == "http://localhost:8317/v1"

    def test_interactive_empty_input_keeps_defaults(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """全程回车——保留默认配置。"""
        self._interactive(monkeypatch)
        # 层级回车=项目级（默认），兼建用户级回车=是，后续配置全回车
        # （11 个：层级/兼建/llm×4/embedding×3/network×2）
        result = runner.invoke(main, ["init", str(tmp_path)], input="\n\n\n\n\n\n\n\n\n\n\n")
        assert result.exit_code == 0, result.output
        data = _settings(tmp_path)
        assert data["llm"]["provider"] == "openai"

    def test_interactive_preserves_existing_comments(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """已有 jsonc 时交互引导更新值，文件注释保留。"""
        # 先非交互创建默认配置（不设 DEEP_OBSIDIAN_INTERACTIVE）
        runner.invoke(main, ["init", str(tmp_path)])
        settings_file = tmp_path / ".deep-obsidian" / "settings.jsonc"
        text = settings_file.read_text(encoding="utf-8")
        assert "勿提交 git" in text  # 模板注释存在

        # 交互式改 provider（选择 custom），其余回车继承
        self._interactive(monkeypatch)
        result = runner.invoke(
            main,
            ["init", str(tmp_path)],
            input=(
                "1\n"  # 层级：项目级
                "y\n"  # 兼建用户级
                "2\n"  # custom
                "\n\n\n\n\n\n\n\n"  # 其余全部回车（含 network 离线确认）
            ),
        )
        assert result.exit_code == 0, result.output
        data = _settings(tmp_path)
        assert data["llm"]["provider"] == "custom"
        # 注释保留
        new_text = settings_file.read_text(encoding="utf-8")
        assert "勿提交 git" in new_text

    def _isolated_home(self, tmp_path: Path, monkeypatch) -> None:
        """把 HOME 指向临时目录，隔离真实机器上的用户级配置。"""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

    def test_interactive_out_of_range_provider_reprompts(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """provider 菜单越界输入（如 5）不得崩溃——click.IntRange 重新询问。"""
        self._interactive(monkeypatch)
        self._isolated_home(tmp_path, monkeypatch)
        result = runner.invoke(
            main,
            ["init", str(tmp_path)],
            input=(
                "1\n"  # 层级：项目级
                "y\n"  # 兼建用户级
                "5\n"  # 越界 → 重问
                "2\n"  # custom
                "\n\n\n\n\n\n\n\n"  # 其余回车（含 network 离线确认）
            ),
        )
        assert result.exit_code == 0, result.output
        assert _settings(tmp_path)["llm"]["provider"] == "custom"

    def test_interactive_password_default_not_echoed(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """已有 API key 时，密码提示不得把 key 明文回显在终端。"""
        self._isolated_home(tmp_path, monkeypatch)
        secret = "sk-super-secret-key-123"
        # 先非交互建带 key 的多行配置
        runner.invoke(main, ["init", str(tmp_path)])
        from deep_obsidian.settings import update_settings

        update_settings(tmp_path, {"llm": {"api_key": secret}})

        self._interactive(monkeypatch)
        result = runner.invoke(
            main,
            ["init", str(tmp_path)],
            input=(
                "1\n"  # 层级：项目级
                "y\n"  # 兼建用户级
                "\n"  # provider 回车继承
                "\n"  # model 回车继承
                "\n"  # api_key 回车保留当前值
                "\n"  # endpoint
                "\n\n\n"  # embedding
                "\n"  # network: hf_endpoint
                "\n"  # network: hf_hub_offline 回车（继承默认不启用）
            ),
        )
        assert result.exit_code == 0, result.output
        assert secret not in result.output, f"API key 在终端回显: {result.output}"
        # key 仍被保留在配置中
        assert _settings(tmp_path)["llm"]["api_key"] == secret

    def test_interactive_inherits_user_level_offline_default(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """向导预填默认值必须用 merge 后的有效配置：项目级留空继承用户级
        hf_hub_offline=true 时，全程回车不得把它静默改成 false（曾只看单层
        配置，把继承的 true 写成显式 false 覆盖掉）。"""
        self._isolated_home(tmp_path, monkeypatch)
        # 非交互建项目 + 用户级（模板），再给用户级写入 hf_hub_offline=true
        runner.invoke(main, ["init", str(tmp_path)])
        from deep_obsidian.settings import resolve_config, update_settings

        home = tmp_path / "home"
        update_settings(home, {"network": {"hf_hub_offline": True}})
        assert (
            resolve_config(vault=tmp_path, cwd=tmp_path).settings["network"]["hf_hub_offline"]
            is True
        )

        # 交互式重跑：用户级已存在 → 不询问兼建；全程回车
        self._interactive(monkeypatch)
        result = runner.invoke(
            main,
            ["init", str(tmp_path)],
            input=(
                "1\n"  # 层级：项目级
                "\n\n\n\n"  # llm: provider/model/api_key/endpoint
                "\n\n\n"  # embedding
                "\n"  # network: hf_endpoint
                "\n"  # network: hf_hub_offline（默认应为 true，回车保持）
            ),
        )
        assert result.exit_code == 0, result.output
        # 有效配置仍是 true——没有被向导静默改成 false
        assert (
            resolve_config(vault=tmp_path, cwd=tmp_path).settings["network"]["hf_hub_offline"]
            is True
        )

    def test_user_level_force_warns_before_deleting_with_full_scope(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """用户级 --force 必须在删除前给出完整范围警告（含 <vault>/.cognee
        知识图谱，曾事后才提示且遗漏 .cognee）。"""
        self._interactive(monkeypatch)
        self._isolated_home(tmp_path, monkeypatch)
        result = runner.invoke(
            main,
            ["init", "--force", str(tmp_path)],
            input=(
                "2\n"  # 层级：用户级
                "\n\n\n\n"  # llm
                "\n\n\n"  # embedding
                "\n\n"  # network
            ),
        )
        assert result.exit_code == 0, result.output
        # 警告出现在输出中：即将执行 + 完整范围（.cognee）
        assert "即将执行用户级 --force" in result.output
        assert ".cognee" in result.output

    def test_interactive_inline_object_fails_loudly_and_keeps_file(  # noqa: E501 - test name is descriptive
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """含单行内联对象的配置文件无法安全更新时，大声失败且不写盘。"""
        self._interactive(monkeypatch)
        self._isolated_home(tmp_path, monkeypatch)
        settings_file = tmp_path / ".deep-obsidian" / "settings.jsonc"
        settings_file.parent.mkdir(parents=True)
        inline = (
            '{\n  "llm": { "provider": "custom", "model": "gpt-4o" },\n'
            '  "embedding": { "provider": "fastembed" }\n}\n'
        )
        settings_file.write_text(inline, encoding="utf-8")

        result = runner.invoke(
            main,
            ["init", str(tmp_path)],
            input=(
                "1\n"  # 层级：项目级
                "y\n"  # 兼建用户级
                "2\n"  # custom
                "gpt-5\n"  # model
                "\n\n\n\n\n\n\n\n"  # 其余回车（含 network 离线确认）
            ),
        )
        assert result.exit_code != 0
        assert "单行内联" in result.output or "展开为多行" in result.output
        # 文件未被写入损坏内容
        assert settings_file.read_text(encoding="utf-8") == inline
