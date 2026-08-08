"""Tests for deep_obsidian.settings module."""

import json
import tempfile
from pathlib import Path

import pytest

from deep_obsidian.settings import find_project_root, init_project, read_settings, write_settings


class TestFindProjectRoot:
    """find_project_root 向上查找 .deep-obsidian/ 目录"""

    def test_finds_in_current_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".deep-obsidian").mkdir()
            (root / ".deep-obsidian" / "settings.json").write_text("{}")
            (root / "sub").mkdir()
            assert find_project_root(root / "sub") == root

    def test_finds_in_parent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".deep-obsidian").mkdir()
            (root / ".deep-obsidian" / "settings.json").write_text("{}")
            deep = root / "a" / "b" / "c"
            deep.mkdir(parents=True)
            assert find_project_root(deep) == root

    def test_returns_none_when_no_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assert find_project_root(root) is None

    def test_returns_none_for_nonexistent_path(self):
        assert find_project_root(Path("/nonexistent/path/12345")) is None

    def test_stops_at_filesystem_root(self):
        """确保不会无限向上查找"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assert find_project_root(root) is None


class TestInitProject:
    """init_project 创建 .deep-obsidian/settings.json"""

    def test_creates_directory_and_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            assert (root / ".deep-obsidian").is_dir()
            assert (root / ".deep-obsidian" / "settings.json").is_file()

    def test_writes_valid_json_with_required_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            data = json.loads((root / ".deep-obsidian" / "settings.json").read_text())
            assert "deep-obsidian-id" in data
            assert "name" in data
            assert "created_at" in data
            assert "last_used_at" in data
            assert "cli_version" in data
            assert "backend" in data
            assert data["backend"]["type"] == "cognee"

    def test_default_name_is_directory_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            data = json.loads((root / ".deep-obsidian" / "settings.json").read_text())
            assert data["name"] == root.name

    def test_explicit_name_overrides_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root, name="my-vault")
            data = json.loads((root / ".deep-obsidian" / "settings.json").read_text())
            assert data["name"] == "my-vault"

    def test_idempotent(self):
        """重复 init 不报错，保留原有数据"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = init_project(root, name="first")
            init_project(root, name="second")
            data = json.loads((root / ".deep-obsidian" / "settings.json").read_text())
            # 不覆盖已有项目
            assert data["deep-obsidian-id"] == first["deep-obsidian-id"]
            assert data["name"] == "first"

    def test_force_clears_existing_state_and_recreates(self):
        """--force 清除所有旧状态后重新创建 — 工厂重置路径。

        Regression: init --force 路径（settings.py:94-101）删除了
        .deep-obsidian/、.cognee/、$HOME/.deep-obsidian/ 三个目录，
        但没有自动化测试验证这一行为。
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # 创建旧状态
            old_settings = root / ".deep-obsidian"
            old_cognee = root / ".cognee"
            old_settings.mkdir()
            (old_settings / "settings.json").write_text('{"name":"old"}')
            old_cognee.mkdir()
            (old_cognee / "stale.db").write_text("stale data")

            # --force 后应该是全新的
            result = init_project(root, name="new-vault", force=True)
            assert result["name"] == "new-vault"

            settings = json.loads((root / ".deep-obsidian" / "settings.json").read_text())
            assert settings["name"] == "new-vault"

            # 旧状态已被清除
            assert not (root / ".cognee").exists(), ".cognee/ should have been removed by force"

    def test_force_with_nonexistent_dir_still_works(self):
        """对不存在的目录 --force 也应该正常创建项目。

        Regression: CLI 的 init 命令允许 `--force` 用于不存在的目录
        （cli.py 中 `if not force and not _target.exists()` 的逻辑），
        但 init_project 本身没有 force + 不存在路径的测试。
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "new-project"
            assert not root.exists()

            result = init_project(root, name="brand-new", force=True)
            assert result["name"] == "brand-new"
            assert root.exists()
            assert (root / ".deep-obsidian" / "settings.json").is_file()


class TestReadWriteSettings:
    """read_settings / write_settings 读写配置"""

    def test_read_returns_parsed_dict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            data = read_settings(root)
            assert isinstance(data, dict)
            assert data["backend"]["type"] == "cognee"

    def test_read_raises_when_no_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with pytest.raises(FileNotFoundError):
                read_settings(root)

    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir()
            data = {"deep-obsidian-id": "test-123", "name": "test", "backend": {"type": "cognee"}}
            write_settings(root, data)
            assert read_settings(root) == data
