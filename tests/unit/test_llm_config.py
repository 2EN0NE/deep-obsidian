"""Tests for _read_llm_config — LLM routing config from settings.jsonc.

ADR-0011/0012: LLM config lives in the top-level ``llm`` section of
settings.jsonc (single source of truth).  Environment variables no
longer override it — the project file is the only source.
"""

from __future__ import annotations

from deep_obsidian.query import _read_llm_config


def _settings_with(**llm_cfg) -> dict:
    return {"llm": llm_cfg}


class TestDefaults:
    def test_no_config_returns_default_model_and_none_optionals(self):
        model, provider, endpoint, api_key = _read_llm_config({})
        assert model == "openai/gpt-5-mini"
        assert provider is None
        assert endpoint is None
        assert api_key is None

    def test_empty_llm_section_returns_defaults(self):
        model, provider, endpoint, api_key = _read_llm_config({"llm": {}})
        assert model == "openai/gpt-5-mini"
        assert provider is None
        assert endpoint is None
        assert api_key is None


class TestSettingsValues:
    """settings.jsonc 顶层 llm.* 字段被正确读取。"""

    def test_llm_values_used(self):
        settings = _settings_with(
            model="gpt-4o",
            provider="openai",
            endpoint="https://api.openai.com/v1",
            api_key="sk-settings-key",
        )
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert model == "gpt-4o"
        assert provider == "openai"
        assert endpoint == "https://api.openai.com/v1"
        assert api_key == "sk-settings-key"

    def test_custom_provider_model_prefix(self):
        settings = _settings_with(
            provider="custom",
            model="openai/deepseek-v4-pro",
            endpoint="http://localhost:8317/v1",
            api_key="sk-test",
        )
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert model == "openai/deepseek-v4-pro"
        assert provider == "custom"
        assert endpoint == "http://localhost:8317/v1"
        assert api_key == "sk-test"


class TestNoEnvPrecedence:
    """ADR-0012：环境变量不再覆盖 jsonc 配置（唯一来源是项目文件）。"""

    def test_env_vars_do_not_override_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "env-model")
        monkeypatch.setenv("LLM_PROVIDER", "env-provider")
        monkeypatch.setenv("LLM_ENDPOINT", "https://env.example.com")
        monkeypatch.setenv("LLM_API_KEY", "sk-env-key")

        settings = _settings_with(
            model="settings-model",
            provider="settings-provider",
            endpoint="https://settings.example.com",
            api_key="sk-settings-key",
        )
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert model == "settings-model"
        assert provider == "settings-provider"
        assert endpoint == "https://settings.example.com"
        assert api_key == "sk-settings-key"

    def test_absent_llm_key_does_not_read_deprecated_backend(self):
        """旧 backend.cognee.* schema 已退役——不读它。"""
        settings = {
            "llm": {},
            "backend": {"type": "cognee", "cognee": {"llm_model": "should-not-win"}},
        }
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert "should-not-win" not in model
        assert provider is None
        assert endpoint is None
        assert api_key is None
