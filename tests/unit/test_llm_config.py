"""Tests for _read_llm_config — settings/env precedence for LLM routing.

Regression: this logic was added without any test coverage even though
it directly controls which LLM provider/endpoint/key a real query()
request is routed to. A wrong precedence or a broken ``custom`` provider
special-case would silently misroute LLM calls in production.
"""

from __future__ import annotations

from deep_obsidian.query import _read_llm_config

_COGNEE_SETTINGS: dict = {"backend": {"type": "cognee", "cognee": {}}}


def _settings_with(**cognee_cfg) -> dict:
    return {"backend": {"type": "cognee", "cognee": cognee_cfg}}


class TestDefaults:
    def test_no_config_returns_default_model_and_none_optionals(self, monkeypatch):
        for var in ("LLM_MODEL", "LLM_PROVIDER", "LLM_ENDPOINT", "LLM_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        model, provider, endpoint, api_key = _read_llm_config(_COGNEE_SETTINGS)
        assert model == "deepseek-chat"
        assert provider is None
        assert endpoint is None
        assert api_key is None

    def test_unsupported_backend_type_raises(self):
        import pytest

        with pytest.raises(RuntimeError, match="Unsupported backend type"):
            _read_llm_config({"backend": {"type": "pinecone"}})


class TestSettingsValues:
    def test_settings_json_values_used_when_no_env(self, monkeypatch):
        for var in ("LLM_MODEL", "LLM_PROVIDER", "LLM_ENDPOINT", "LLM_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        settings = _settings_with(
            llm_model="gpt-4o",
            llm_provider="openai",
            llm_endpoint="https://api.openai.com/v1",
            llm_api_key="sk-settings-key",
        )
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert model == "gpt-4o"
        assert provider == "openai"
        assert endpoint == "https://api.openai.com/v1"
        assert api_key == "sk-settings-key"


class TestEnvPrecedence:
    """Env vars must win over settings.json for all four fields."""

    def test_env_model_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "env-model")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_ENDPOINT", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        settings = _settings_with(llm_model="settings-model")
        model, _, _, _ = _read_llm_config(settings)
        assert model == "env-model"

    def test_env_provider_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "env-provider")
        settings = _settings_with(llm_provider="settings-provider")
        _, provider, _, _ = _read_llm_config(settings)
        assert provider == "env-provider"

    def test_env_endpoint_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_ENDPOINT", "https://env.example.com")
        settings = _settings_with(llm_endpoint="https://settings.example.com")
        _, _, endpoint, _ = _read_llm_config(settings)
        assert endpoint == "https://env.example.com"

    def test_env_api_key_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-env-key")
        settings = _settings_with(llm_api_key="sk-settings-key")
        _, _, _, api_key = _read_llm_config(settings)
        assert api_key == "sk-env-key"

    def test_all_four_env_vars_together_override_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "env-model")
        monkeypatch.setenv("LLM_PROVIDER", "env-provider")
        monkeypatch.setenv("LLM_ENDPOINT", "https://env.example.com")
        monkeypatch.setenv("LLM_API_KEY", "sk-env-key")

        settings = _settings_with(
            llm_model="settings-model",
            llm_provider="settings-provider",
            llm_endpoint="https://settings.example.com",
            llm_api_key="sk-settings-key",
        )
        model, provider, endpoint, api_key = _read_llm_config(settings)
        assert model == "env-model"
        assert provider == "env-provider"
        assert endpoint == "https://env.example.com"
        assert api_key == "sk-env-key"
