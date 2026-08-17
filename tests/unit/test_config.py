"""Tests for deep_obsidian.config — Cognee config injection (ADR-0012).

Validates that LLM/Embedding settings from settings.jsonc are injected
via cognee.config.set_*_config() and network settings via os.environ,
without touching the real Cognee API (mocked).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from deep_obsidian.settings import init_project


def _write_custom_settings(root: Path) -> dict:
    """Write a settings.jsonc with realistic LLM/Embedding/network values."""
    init_project(root, name="test-vault")
    from deep_obsidian.settings import update_settings

    update_settings(
        root,
        {
            "llm": {
                "provider": "custom",
                "model": "openai/deepseek-v4-pro",
                "api_key": "sk-test-123",
                "endpoint": "http://localhost:8317/v1",
            },
            "embedding": {
                "provider": "fastembed",
                "model": "BAAI/bge-small-zh-v1.5",
                "dimensions": 512,
            },
            "network": {
                "hf_endpoint": "https://hf-mirror.com",
                "hf_hub_offline": True,
                "cognee_skip_connection_test": True,
            },
        },
    )
    return read_settings(root)


def read_settings(root: Path) -> dict:
    from deep_obsidian.settings import read_settings as _r

    return _r(root)


class TestInjectFromResolvedConfig:
    """从 merge 后的 ResolvedConfig 注入 Cognee（ADR-0012 + ADR-0014）"""

    def test_injects_llm_config(self, tmp_path, monkeypatch):
        """项目级配置（merge 用户级）注入。"""
        # 用户级基础层
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        from deep_obsidian.settings import init_project as _init
        from deep_obsidian.settings import resolve_config

        _init(tmp_path, name="u", level="user")
        _write_custom_settings(tmp_path)
        res = resolve_config(vault=tmp_path, cwd=tmp_path)
        from deep_obsidian.config import inject_config as config_inject

        with (
            patch("cognee.config.set_llm_config") as mock_llm,
            patch("cognee.config.set_embedding_config") as mock_emb,
        ):
            config_inject(res)

        mock_llm.assert_called_once_with(
            {
                "llm_provider": "custom",
                "llm_model": "openai/deepseek-v4-pro",
                "llm_api_key": "sk-test-123",
                "llm_endpoint": "http://localhost:8317/v1",
            }
        )
        mock_emb.assert_called_once_with(
            {
                "embedding_provider": "fastembed",
                "embedding_model": "BAAI/bge-small-zh-v1.5",
                "embedding_dimensions": 512,
            }
        )

    def test_injects_network_env_vars(self, tmp_path, monkeypatch):
        _init_user_home(tmp_path, monkeypatch)
        _write_custom_settings(tmp_path)
        from deep_obsidian.config import inject_config as config_inject
        from deep_obsidian.settings import resolve_config

        # 清理环境，确保注入真正设置（而非继承宿主机）
        monkeypatch.delenv("HF_ENDPOINT", raising=False)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.delenv("COGNEE_SKIP_CONNECTION_TEST", raising=False)

        with patch("cognee.config.set_llm_config"), patch("cognee.config.set_embedding_config"):
            config_inject(resolve_config(vault=tmp_path, cwd=tmp_path))

        assert os.getenv("HF_ENDPOINT") == "https://hf-mirror.com"
        assert os.getenv("HF_HUB_OFFLINE") == "true"
        assert os.getenv("COGNEE_SKIP_CONNECTION_TEST") == "true"

    def test_false_network_value_not_injected(self, tmp_path, monkeypatch):
        """False 布尔不注入：runtime 库把非空字符串当真值，"false" 会误启离线。"""
        _init_user_home(tmp_path, monkeypatch)
        init_project(tmp_path, name="t")
        from deep_obsidian.settings import resolve_config, update_settings

        update_settings(tmp_path, {"network": {"hf_hub_offline": False}})
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

        from deep_obsidian.config import inject_config as config_inject

        with patch("cognee.config.set_llm_config"), patch("cognee.config.set_embedding_config"):
            config_inject(resolve_config(vault=tmp_path, cwd=tmp_path))

        assert os.getenv("HF_HUB_OFFLINE") is None

    def test_false_network_value_clears_existing_env(self, tmp_path, monkeypatch):
        """显式 false 必须清除环境中已残留的同名变量（修复：曾只"不注入"，
        残留的 true——shell export 或先前注入——会继续生效，覆盖 settings 的
        显式关闭意图）。"""
        _init_user_home(tmp_path, monkeypatch)
        init_project(tmp_path, name="t")
        from deep_obsidian.settings import resolve_config, update_settings

        update_settings(tmp_path, {"network": {"hf_hub_offline": False}})
        monkeypatch.setenv("HF_HUB_OFFLINE", "true")  # 模拟 shell export 残留

        from deep_obsidian.config import inject_config as config_inject

        with patch("cognee.config.set_llm_config"), patch("cognee.config.set_embedding_config"):
            config_inject(resolve_config(vault=tmp_path, cwd=tmp_path))

        assert os.getenv("HF_HUB_OFFLINE") is None

    def test_injects_default_config_without_network(self, tmp_path, monkeypatch):
        """无 network 段时干净退出。"""
        _init_user_home(tmp_path, monkeypatch)
        init_project(tmp_path, name="t")
        from deep_obsidian.config import inject_config as config_inject
        from deep_obsidian.settings import resolve_config

        with patch("cognee.config.set_llm_config"), patch("cognee.config.set_embedding_config"):
            config_inject(resolve_config(vault=tmp_path, cwd=tmp_path))


def _init_user_home(tmp_path, monkeypatch) -> None:
    """创建用户级配置（merge 基础层）。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    from deep_obsidian.settings import init_project as _init

    _init(tmp_path, name="u", level="user")


class TestInjectionIdempotent:
    """重复注入不报错（setter 幂等）。"""

    def test_inject_twice(self, tmp_path, monkeypatch):
        _init_user_home(tmp_path, monkeypatch)
        _write_custom_settings(tmp_path)
        from deep_obsidian.config import inject_config as config_inject
        from deep_obsidian.settings import resolve_config

        res = resolve_config(vault=tmp_path, cwd=tmp_path)
        with patch("cognee.config.set_llm_config"), patch("cognee.config.set_embedding_config"):
            config_inject(res)
            config_inject(res)
