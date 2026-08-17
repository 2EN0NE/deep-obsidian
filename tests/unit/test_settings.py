"""Tests for deep_obsidian.settings — settings.jsonc (JSONC with comments)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from deep_obsidian.settings import (
    SETTINGS_DIR,
    SETTINGS_FILE,
    find_project_root,
    init_project,
    read_settings,
    update_settings,
    write_settings,
)

TEMPLATE_JSONC = """\
{
  // 此文件含 API key，勿提交 git
  "deep-obsidian-id": "uuid",
  "name": "my-vault",
  "created_at": "2025-01-01T00:00:00+00:00",

  // Cognee LLM 配置
  "llm": {
    "provider": "openai",  // 可选: openai, custom, ollama
    "model": "gpt-4o",
    "api_key": "",
    "endpoint": ""
  },

  // Cognee Embedding 配置
  "embedding": {
    "provider": "fastembed",
    "model": "BAAI/bge-small-en-v1.5",
    "dimensions": 384
  }
}
"""


class TestFindProjectRoot:
    """find_project_root 向上查找 .deep-obsidian/ 目录（须含 settings.jsonc）"""

    def test_finds_in_current_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".deep-obsidian").mkdir()
            (root / ".deep-obsidian" / SETTINGS_FILE).write_text("{}")
            (root / "sub").mkdir()
            assert find_project_root(root / "sub") == root

    def test_finds_in_parent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".deep-obsidian").mkdir()
            (root / ".deep-obsidian" / SETTINGS_FILE).write_text("{}")
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
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assert find_project_root(root) is None

    def test_ignores_dir_without_settings_jsonc(self):
        """只有 .deep-obsidian/ 目录但无 settings.jsonc，不算项目根。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir()
            (root / ".deep-obsidian" / "hashes.json").write_text("{}")
            assert find_project_root(root) is None


class TestInitProject:
    """init_project 创建 .deep-obsidian/settings.jsonc"""

    def test_creates_directory_and_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            assert (root / ".deep-obsidian").is_dir()
            assert (root / ".deep-obsidian" / SETTINGS_FILE).is_file()

    def test_writes_valid_jsonc_with_required_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            data = read_settings(root)
            assert "deep-obsidian-id" in data
            assert "name" in data
            assert "created_at" in data
            assert "last_used_at" in data
            assert "cli_version" in data
            assert "llm" in data
            assert data["llm"]["provider"] in ("openai", "custom")

    def test_default_network_offline_not_set(self):
        """模板不预设 hf_hub_offline（缺失 = 在线）：首次 ingest 需联网下载
        embedding 模型（~100MB，USER_GUIDE 明确警告首次不可离线）。曾默认
        true 导致新用户首次 ingest 被 HF_HUB_OFFLINE 阻止而失败；预设 false
        又会通过 merge 压制用户级显式 true（回归保护）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            data = read_settings(root)
            assert "hf_hub_offline" not in data["network"]

    def test_template_contains_comment_header(self):
        """模板文件头必须有提示注释（ADR-0011: 勿提交 git）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            text = (root / ".deep-obsidian" / SETTINGS_FILE).read_text(encoding="utf-8")
            assert "勿提交" in text or "API key" in text

    def test_default_name_is_directory_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root)
            data = read_settings(root)
            assert data["name"] == root.name

    def test_explicit_name_overrides_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root, name="my-vault")
            data = read_settings(root)
            assert data["name"] == "my-vault"

    def test_idempotent(self):
        """重复 init 不报错，保留原有数据"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = init_project(root, name="first")
            init_project(root, name="second")
            data = read_settings(root)
            assert data["deep-obsidian-id"] == first["deep-obsidian-id"]
            assert data["name"] == "first"

    def test_force_clears_existing_state_and_recreates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_settings = root / ".deep-obsidian"
            old_cognee = root / ".cognee"
            old_settings.mkdir()
            (old_settings / SETTINGS_FILE).write_text('{"name":"old"}')
            old_cognee.mkdir()
            (old_cognee / "stale.db").write_text("stale data")

            result = init_project(root, name="new-vault", force=True)
            assert result["name"] == "new-vault"

            settings = read_settings(root)
            assert settings["name"] == "new-vault"
            assert not (root / ".cognee").exists()

    def test_force_with_nonexistent_dir_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "new-project"
            assert not root.exists()

            result = init_project(root, name="brand-new", force=True)
            assert result["name"] == "brand-new"
            assert root.exists()
            assert (root / ".deep-obsidian" / SETTINGS_FILE).is_file()

    def test_project_level_force_preserves_user_level_config(self, monkeypatch):
        """项目级 --force 不得删除 ~/.deep-obsidian/（ADR-0014 必需基础层）——
        那里有用户级 API key、vault 注册表和其他 vault 的用户级 hashes。
        """
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            monkeypatch.setenv("HOME", str(home))

            # 构造用户级基础层 + 另一个 vault 的注册表条目
            from deep_obsidian.settings import register_vault

            init_project(home / "vaultA", name="vaultA", level="user")
            # user_dir 是 .deep-obsidian 目录本身（与 cli.vaults 一致）
            register_vault(home / SETTINGS_DIR, home / "vaultB")
            user_settings = (home / SETTINGS_DIR / SETTINGS_FILE).read_text(encoding="utf-8")

            # 项目级 force（默认 level=project）
            root = home / "vaultA"
            init_project(root, name="vaultA", force=True, level="project")

            # 用户级配置与注册表必须原样保留
            user_file = home / SETTINGS_DIR / SETTINGS_FILE
            assert user_file.is_file()
            assert user_file.read_text(encoding="utf-8") == user_settings
            index = home / SETTINGS_DIR / "vaults" / "index.json"
            assert index.is_file(), "vault 注册表被项目级 force 删除了"


class TestReadWriteSettings:
    """read_settings / write_settings 读写 jsonc"""

    def test_read_returns_parsed_dict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            (root / ".deep-obsidian" / SETTINGS_FILE).write_text(TEMPLATE_JSONC)
            data = read_settings(root)
            assert data["name"] == "my-vault"
            assert data["llm"]["provider"] == "openai"
            assert data["embedding"]["dimensions"] == 384

    def test_read_ignores_comments(self):
        """jsonc 注释不影响解析。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            (root / ".deep-obsidian" / SETTINGS_FILE).write_text(TEMPLATE_JSONC)
            data = read_settings(root)
            assert "可选" not in str(data)  # 注释没有被解析进 dict

    def test_read_raises_when_no_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with pytest.raises(FileNotFoundError):
                read_settings(root)

    def test_write_and_read_roundtrip(self):
        """write_settings 是模板基写：data 中的值覆盖模板默认值。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir()
            data = {
                "deep-obsidian-id": "test-123",
                "name": "test",
                "llm": {"provider": "custom", "model": "gpt-4o"},
            }
            write_settings(root, data)
            read = read_settings(root)
            # data 中的值全部生效
            assert read["deep-obsidian-id"] == "test-123"
            assert read["name"] == "test"
            assert read["llm"]["provider"] == "custom"
            assert read["llm"]["model"] == "gpt-4o"
            # 模板默认字段仍存在（embedding / network 未被覆盖）
            assert "embedding" in read
            assert read["embedding"]["provider"] == "fastembed"
            assert "network" in read


class TestUpdateSettings:
    """update_settings — 注释感知的键值更新（保留注释与未碰字段）"""

    def test_updates_leaf_value_preserving_comments(self):
        """只替换目标叶子值，行内注释保留。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(TEMPLATE_JSONC)

            update_settings(root, {"llm": {"provider": "custom"}})

            text = p.read_text(encoding="utf-8")
            # 行内注释保留
            assert "// 可选: openai, custom, ollama" in text
            # 值已更新
            assert '"provider": "custom"' in text
            # 未碰字段不变
            assert read_settings(root)["llm"]["model"] == "gpt-4o"

    def test_updates_multiple_leaves(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(TEMPLATE_JSONC)

            update_settings(
                root,
                {
                    "llm": {"model": "deepseek-chat", "api_key": "sk-123"},
                    "embedding": {"dimensions": 512},
                },
            )

            data = read_settings(root)
            assert data["llm"]["model"] == "deepseek-chat"
            assert data["llm"]["api_key"] == "sk-123"
            assert data["embedding"]["dimensions"] == 512

    def test_preserves_untouched_sections_verbatim(self):
        """未更新的 section 保持原文（含其内部注释与缩进）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(TEMPLATE_JSONC)

            update_settings(root, {"llm": {"provider": "custom"}})

            text = p.read_text(encoding="utf-8")
            # embedding section 原文未动
            assert "BAAI/bge-small-en-v1.5" in text
            assert '"dimensions": 384' in text

    def test_adds_new_key_when_absent(self):
        """目标键不存在时插入到对应对象块内。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(TEMPLATE_JSONC)

            update_settings(root, {"network": {"hf_endpoint": "https://hf-mirror.com"}})

            data = read_settings(root)
            assert data["network"]["hf_endpoint"] == "https://hf-mirror.com"
            # 原有注释仍在
            text = p.read_text(encoding="utf-8")
            assert "勿提交" in text

    def test_writes_are_atomic(self):
        """update_settings 必须原子写（临时文件 + os.replace）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(TEMPLATE_JSONC)

            update_settings(root, {"llm": {"provider": "custom"}})

            # 无残留临时文件
            leftovers = [f for f in p.parent.iterdir() if f.name != SETTINGS_FILE]
            assert leftovers == []

    def test_roundtrip_after_update_is_valid_jsonc(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(TEMPLATE_JSONC)

            update_settings(root, {"llm": {"provider": "custom"}})
            # 更新后仍能被解析
            data = read_settings(root)
            assert data["llm"]["provider"] == "custom"

    def test_inline_object_raises_and_does_not_write(self):
        """单行内联对象（"llm": {...} 写在一行）无法安全更新时大声失败，
        且绝不写盘——静默损坏配置（更新落到错误层级/重复键）是数据错误。
        """
        inline = (
            '{\n  "llm": { "provider": "custom", "model": "gpt-4o" },\n'
            '  "embedding": { "provider": "fastembed" }\n}\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(inline)

            with pytest.raises(ValueError, match="单行内联对象|展开为多行"):
                update_settings(root, {"llm": {"model": "gpt-5"}})

            # 文件必须保持原样（未被写入损坏内容）
            assert p.read_text(encoding="utf-8") == inline

    def test_closing_brace_with_trailing_comment_updates_correctly(self):
        """花括号带尾注释（}, // xxx）不得破坏嵌套跟踪。"""
        text = (
            '{\n  "llm": {\n    "provider": "custom",  // 注释\n'
            '    "model": "gpt-4o"\n  }, // llm 段结束\n'
            '  "embedding": {\n    "provider": "fastembed"\n  }\n}\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(text)

            update_settings(
                root,
                {"llm": {"model": "gpt-5"}, "embedding": {"dimensions": 768}},
            )

            data = read_settings(root)
            assert data["llm"]["model"] == "gpt-5"
            assert data["embedding"]["dimensions"] == 768
            # 注释仍在
            assert "llm 段结束" in p.read_text(encoding="utf-8")

    def test_trailing_block_comment_preserved_on_rewrite(self):
        """行尾 /* */ 块注释必须逐字保留（曾被视为值的一部分而静默丢弃），
        注释前的空格也不丢失——契约是"除目标值外全部原样"。"""
        text = (
            '{\n  "llm": {\n'
            '    "provider": "openai" /* 行尾块注释 */,\n'
            '    "model": "gpt-4o"\n  }\n}\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(text)

            update_settings(root, {"llm": {"provider": "custom"}})

            data = read_settings(root)
            assert data["llm"]["provider"] == "custom"
            new_text = p.read_text(encoding="utf-8")
            assert "/* 行尾块注释 */" in new_text
            assert '"custom" /* 行尾块注释 */' in new_text  # 注释前的空格保留

    def test_compact_block_comment_no_space_preserved(self):
        """无空格的紧凑块注释（"v"/* c */）同样保留。"""
        text = '{\n  "llm": {\n    "provider": "openai"/*紧凑*/\n  }\n}\n'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".deep-obsidian").mkdir(parents=True)
            p = root / ".deep-obsidian" / SETTINGS_FILE
            p.write_text(text)

            update_settings(root, {"llm": {"provider": "custom"}})

            data = read_settings(root)
            assert data["llm"]["provider"] == "custom"
            assert "/*紧凑*/" in p.read_text(encoding="utf-8")


class TestJsoncScannerRegressions:
    """审查发现的扫描器静默写坏回归（原单行数组/无关内联对象会产生
    重复键并静默丢失兄弟字段，绕过 fail-loud 契约）。"""

    def _write(self, root: Path, text: str) -> Path:
        (root / ".deep-obsidian").mkdir(parents=True)
        p = root / ".deep-obsidian" / SETTINGS_FILE
        p.write_text(text)
        return p

    def test_single_line_array_does_not_break_updates(self):
        """单行数组不再吞掉整个文档：更新其他段正常生效、无重复键。"""
        text = (
            '{\n  "tags": ["a", "b"],\n'
            '  "llm": {\n    "provider": "openai",\n    "model": "gpt-4o"\n  }\n}\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = self._write(root, text)

            update_settings(root, {"llm": {"model": "gpt-5"}})

            data = read_settings(root)
            assert data["tags"] == ["a", "b"]
            assert data["llm"] == {"provider": "openai", "model": "gpt-5"}
            # 无重复键
            assert p.read_text(encoding="utf-8").count('"llm"') == 1

    def test_array_with_brackets_in_strings(self):
        """数组字符串内含括号（"a[0]"/"b]c"）不干扰数组跳越与后续键。"""
        text = '{\n  "tags": ["a[0]", "b]c"],\n  "llm": {\n    "model": "gpt-4o"\n  }\n}\n'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, text)

            update_settings(root, {"llm": {"model": "gpt-5"}})

            data = read_settings(root)
            assert data["tags"] == ["a[0]", "b]c"]
            assert data["llm"]["model"] == "gpt-5"

    def test_multiline_array_still_works(self):
        text = (
            '{\n  "tags": [\n    "a",\n    "b"\n  ],\n  "llm": {\n    "model": "gpt-4o"\n  }\n}\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, text)

            update_settings(root, {"llm": {"model": "gpt-5"}})

            data = read_settings(root)
            assert data["tags"] == ["a", "b"]
            assert data["llm"]["model"] == "gpt-5"

    def test_unrelated_inline_object_does_not_corrupt_other_section(self):
        """无关段写成单行内联不再使其他段（多行）的更新产生重复键。"""
        text = (
            '{\n  "llm": { "provider": "custom" },\n  "network": {\n    "hf_endpoint": ""\n  }\n}\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = self._write(root, text)

            update_settings(root, {"network": {"hf_endpoint": "https://hf-mirror.com"}})

            data = read_settings(root)
            assert data["llm"]["provider"] == "custom"  # 无关段原样保留
            assert data["network"]["hf_endpoint"] == "https://hf-mirror.com"
            assert p.read_text(encoding="utf-8").count('"network"') == 1

    def test_array_value_update_fails_loudly(self):
        """数组值本身不在支持范围内：大声失败而非静默产生重复键。"""
        text = '{\n  "tags": ["a"],\n  "llm": {\n    "model": "g"\n  }\n}\n'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = self._write(root, text)

            with pytest.raises(ValueError, match="单行内联对象|展开为多行"):
                update_settings(root, {"tags": ["x"]})

            assert p.read_text(encoding="utf-8") == text
