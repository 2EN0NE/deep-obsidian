"""Tests for deep_obsidian.settings.resolve_config — 三级配置层级解析（ADR-0014）.

接缝：resolve_config() 纯函数（tmp_path 构造层级），不触碰 Cognee。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_obsidian.settings import (
    hashes_path_for,
    init_project,
    read_settings,
    resolve_config,
    vault_path_hash,
)

USER_SETTINGS = """\
{
  "deep-obsidian-id": "user-uuid",
  "name": "user-default",
  "llm": {
    "provider": "openai",
    "model": "openai/gpt-5-mini",
    "api_key": "user-key",
    "endpoint": ""
  },
  "embedding": {
    "provider": "fastembed",
    "model": "BAAI/bge-small-en-v1.5",
    "dimensions": 384
  },
  "network": {
    "hf_endpoint": "https://hf-mirror.com",
    "hf_hub_offline": true,
    "cognee_skip_connection_test": true
  }
}
"""

PROJECT_SETTINGS = """\
{
  "deep-obsidian-id": "proj-uuid",
  "name": "my-vault",
  "llm": {
    "provider": "custom",
    "model": "openai/deepseek-v4-pro",
    "api_key": "",
    "endpoint": "http://localhost:8317/v1"
  }
}
"""


@pytest.fixture
def user_home(tmp_path: Path, monkeypatch) -> Path:
    """构造 ~/.deep-obsidian/settings.jsonc（用户级），并让 HOME 指向 tmp_path。"""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".deep-obsidian").mkdir(parents=True)
    (home / ".deep-obsidian" / "settings.jsonc").write_text(USER_SETTINGS, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """构造带 .deep-obsidian/settings.jsonc 的项目根（PROJECT_SETTINGS 内容）。"""
    root = tmp_path / "vault"
    root.mkdir()
    init_project(root, name="my-vault")
    import json5

    from deep_obsidian.settings import update_settings

    update_settings(root, json5.loads(PROJECT_SETTINGS))
    return root


class TestVaultPathHash:
    """vault 路径 hash：确定性、长度 8、区分不同路径。"""

    def test_deterministic(self):
        a = vault_path_hash(Path("/some/vault"))
        b = vault_path_hash(Path("/some/vault"))
        assert a == b

    def test_eight_chars(self):
        assert len(vault_path_hash(Path("/some/vault"))) == 8

    def test_different_paths_differ(self):
        assert vault_path_hash(Path("/a/vault")) != vault_path_hash(Path("/b/vault"))

    def test_resolves_symlinks_before_hash(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        assert vault_path_hash(link) == vault_path_hash(real)


class TestHashesPathFor:
    """hashes 文件位置：项目级 vs 用户级（ADR-0014）。"""

    def test_project_level(self, tmp_path: Path):
        project_root = tmp_path / "proj"
        vault = tmp_path / "vault"
        got = hashes_path_for(vault, project_root, "project")
        assert got == project_root / "vault" / "hashes.json"

    def test_config_level_same_as_project(self, tmp_path: Path):
        project_root = tmp_path / "proj"
        vault = tmp_path / "vault"
        got = hashes_path_for(vault, project_root, "config")
        assert got == project_root / "vault" / "hashes.json"

    def test_user_level_uses_vault_hash(self, tmp_path: Path):
        user_dir = tmp_path / "user"
        vault = tmp_path / "vault"
        got = hashes_path_for(vault, user_dir, "user")
        assert got == user_dir / "vaults" / vault_path_hash(vault) / "hashes.json"


class TestResolveConfig:
    """resolve_config：三级查找 + 深度 merge（ADR-0014）。"""

    def test_user_level_only(self, user_home: Path, tmp_path: Path):
        """只有用户级配置时，直接用用户级。"""
        res = resolve_config(vault=tmp_path / "vault", cwd=tmp_path)
        assert res.level == "user"
        assert res.settings["llm"]["api_key"] == "user-key"
        assert res.settings["name"] == "user-default"
        expected = (
            user_home
            / ".deep-obsidian"
            / "vaults"
            / vault_path_hash(tmp_path / "vault")
            / "hashes.json"
        )
        assert res.hashes_path == expected

    def test_project_overrides_user(self, user_home: Path, project: Path):
        """项目级覆盖用户级冲突键；用户级独有键保留（深度 merge）。"""
        res = resolve_config(vault=project, cwd=project)
        assert res.level == "project"
        # 项目级覆盖
        assert res.settings["llm"]["provider"] == "custom"
        assert res.settings["llm"]["endpoint"] == "http://localhost:8317/v1"
        # 用户级独有键保留（项目级没有 embedding）
        assert res.settings["embedding"]["model"] == "BAAI/bge-small-en-v1.5"
        # 项目级 api_key 为空 → 非空才覆盖 → 继承用户级 key
        assert res.settings["llm"]["api_key"] == "user-key"

    def test_project_name_wins(self, user_home: Path, project: Path):
        res = resolve_config(vault=project, cwd=project)
        assert res.settings["name"] == "my-vault"  # 项目级 name 覆盖用户级

    def test_explicit_config_overrides_all(self, user_home: Path, project: Path, tmp_path: Path):
        """--config 显式指定最高优先级，且不再向上查找。"""
        explicit = tmp_path / "explicit" / "settings.jsonc"
        explicit.parent.mkdir()
        explicit.write_text(
            '{"name": "explicit-name", "llm": {"provider": "ollama", "api_key": "exp-key"}}',
            encoding="utf-8",
        )
        res = resolve_config(vault=project, cwd=project, config_path=explicit)
        assert res.level == "config"
        assert res.settings["name"] == "explicit-name"
        assert res.settings["llm"]["provider"] == "ollama"
        # 未在 --config 中声明的键仍从下层继承
        assert res.settings["llm"]["endpoint"] == "http://localhost:8317/v1"

    def test_missing_user_level_raises(self, tmp_path: Path, monkeypatch):
        """用户级是必需基础层——缺失时报错（ADR-0014）。"""
        home = tmp_path / "nohome"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        with pytest.raises(RuntimeError, match="用户级"):
            resolve_config(vault=tmp_path / "vault", cwd=tmp_path)

    def test_missing_user_level_message_points_to_real_command(self, tmp_path: Path, monkeypatch):
        """缺失用户级的提示必须指向真实可执行的命令（曾引用不存在的
        `init --user`，用户按提示操作撞上 No such option）。"""
        home = tmp_path / "nohome"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        with pytest.raises(RuntimeError) as excinfo:
            resolve_config(vault=tmp_path / "vault", cwd=tmp_path)
        msg = str(excinfo.value)
        assert "init --user" not in msg
        assert "deep-obsidian init" in msg  # 提示真实命令

    def test_network_section_merged(self, user_home: Path, project: Path):
        """network 段也参与深度 merge。"""
        res = resolve_config(vault=project, cwd=project)
        assert res.settings["network"]["hf_endpoint"] == "https://hf-mirror.com"
        assert res.settings["network"]["hf_hub_offline"] is True

    def test_vault_resolution(self, user_home: Path, project: Path):
        """vault 显式传入；未传时用 cwd。"""
        res = resolve_config(vault=project, cwd=project)
        assert res.vault == project.resolve()
        res2 = resolve_config(vault=None, cwd=project)
        assert res2.vault == project.resolve()

    def test_config_dir_points_to_most_specific(self, user_home: Path, project: Path):
        """config_dir 指向最个性化层级所在目录。"""
        res = resolve_config(vault=project, cwd=project)
        assert res.config_dir == project / ".deep-obsidian"
        res_user = resolve_config(vault=user_home, cwd=user_home)
        assert res_user.config_dir == user_home / ".deep-obsidian"

    def test_to_dict_roundtrip(self, user_home: Path, project: Path):
        res = resolve_config(vault=project, cwd=project)
        d = res.to_dict()
        assert d["level"] == "project"
        assert d["settings"]["name"] == "my-vault"
        assert "vault" in d and "hashes_path" in d

    def test_single_file_vault_resolves_to_parent(self, user_home: Path, project: Path):
        """单文件目标（ingest 传单个 .md）：vault 解析为其所在目录 ——
        rel 路径、.cognee/ 与 hashes 都挂在目录上，与整库入库的命名空间
        一致（回归：曾把文件本身当 vault，导致 hashes 键退化为 "." 且
        .cognee/ 被指向文件路径之下、单文件 ingest 崩溃）。"""
        note = project / "note.md"
        note.write_text("# hi", encoding="utf-8")

        res = resolve_config(vault=note, cwd=project)

        assert res.vault == project.resolve()
        assert res.level == "project"
        assert res.hashes_path == project / ".deep-obsidian" / "vault" / "hashes.json"


class TestInitProjectLevels:
    """init_project 支持项目级/用户级层级。"""

    def test_init_project_creates_user_level(self, tmp_path: Path, monkeypatch):
        """init_project(level="user") 创建 ~/.deep-obsidian/settings.jsonc。"""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        init_project(tmp_path / "vault", name="v", level="user")
        cfg = read_settings(home)  # read_settings(~) → ~/.deep-obsidian/settings.jsonc
        assert cfg["name"] == "v"

    def test_init_project_defaults_to_project_level(self, tmp_path: Path):
        root = tmp_path / "vault"
        root.mkdir()
        init_project(root, name="v")
        assert (root / ".deep-obsidian" / "settings.jsonc").is_file()

    def test_init_project_force_user_level_resets(self, tmp_path: Path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        init_project(tmp_path / "vault", name="v1", level="user")
        init_project(tmp_path / "vault", name="v2", level="user", force=True)
        cfg = read_settings(home)
        assert cfg["name"] == "v2"
