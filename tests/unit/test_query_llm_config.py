"""Tests for deep_obsidian.query — LLM config resolution from new jsonc schema.

ADR-0011/0012: settings.jsonc 顶层 llm.* 取代 backend.cognee.*；
query 的 litellm 配置从 jsonc 读取，不再依赖环境变量。
"""

from __future__ import annotations

from pathlib import Path

from deep_obsidian.settings import init_project, update_settings


def _make_vault(tmp_path: Path, llm: dict | None = None) -> tuple[Path, Path]:
    """Create an initialized vault with a note; return (vault, project_root)."""
    root = Path(tmp_path)
    init_project(root, name="test-vault")
    if llm:
        update_settings(root, {"llm": llm})
    (root / "note.md").write_text("# hello world")
    return root, root


class TestReadLLMConfig:
    """_read_llm_config 从 settings.jsonc 顶层 llm.* 读取"""

    def test_reads_custom_provider_fields(self, tmp_path):
        root, _ = _make_vault(
            tmp_path,
            {
                "provider": "custom",
                "model": "openai/deepseek-v4-pro",
                "api_key": "sk-test",
                "endpoint": "http://localhost:8317/v1",
            },
        )
        from deep_obsidian.query import _read_llm_config
        from deep_obsidian.settings import read_settings

        settings = read_settings(root)
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert model == "openai/deepseek-v4-pro"
        assert provider == "custom"
        assert endpoint == "http://localhost:8317/v1"
        assert api_key == "sk-test"

    def test_defaults_when_fields_absent(self, tmp_path):
        """新模板只有 llm.provider/model 时，endpoint/api_key 应为 None。"""
        root, _ = _make_vault(tmp_path)
        from deep_obsidian.query import _read_llm_config
        from deep_obsidian.settings import read_settings

        settings = read_settings(root)
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert model  # 模板默认 model 存在
        assert provider == "openai"
        assert endpoint is None
        assert api_key is None

    def test_no_longer_reads_backend_key(self, tmp_path):
        """旧 backend.cognee.* schema 已退役 —— 只读顶层 llm.*。"""
        root, _ = _make_vault(tmp_path)
        from deep_obsidian.query import _read_llm_config
        from deep_obsidian.settings import read_settings

        settings = read_settings(root)
        # 即使 settings 里塞一个废弃的 backend 键，也不影响结果
        settings["backend"] = {"type": "cognee", "cognee": {"llm_model": "should-not-win"}}
        model, _provider, _endpoint, _api_key = _read_llm_config(settings)
        assert "should-not-win" not in model
