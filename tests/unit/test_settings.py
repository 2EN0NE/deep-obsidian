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
