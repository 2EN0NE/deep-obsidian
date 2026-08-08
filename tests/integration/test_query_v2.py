"""Integration tests for query (LLM-synthesized answers)."""

import pytest


class TestQueryRequiresInit:
    """query 在未初始化的目录上必须报错"""

    def test_query_without_init_raises(self, tmp_path):
        import asyncio

        from deep_obsidian.query import query

        with pytest.raises(RuntimeError, match="init"):
            asyncio.run(query("what is a habit?", vault_path=str(tmp_path)))

    def test_query_after_ingest_returns_dict(self, tmp_path, mock_llm):
        """init + ingest 后 query 返回 {answer, sources}（可能走 fallback）"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        (tmp_path / "science.md").write_text("# Science\n\nF = ma. Newton's second law.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        asyncio.run(ingest(str(tmp_path)))
        result = asyncio.run(query("what is Newton's second law?", vault_path=str(tmp_path)))

        assert isinstance(result, dict)
        assert "answer" in result
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0
        assert "sources" in result
        assert isinstance(result["sources"], list)

    def test_query_empty_vault_returns_answer(self, tmp_path, mock_llm):
        """空 vault 的 query 不崩溃"""
        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        init_project(tmp_path, name="empty-vault")

        import asyncio

        result = asyncio.run(query("anything", vault_path=str(tmp_path)))
        assert "answer" in result
        assert "sources" in result
        assert len(result["answer"]) > 0


class TestQueryLLMRouting:
    """query() must build litellm kwargs from settings/env correctly.

    Regression: _read_llm_config's env-var precedence and the
    ``llm_provider == "custom"`` special-case (litellm should infer the
    provider from the model prefix instead of receiving
    ``custom_llm_provider="custom"``, which breaks routing) were both
    added without any test verifying what actually reaches litellm.

    Note: ``import cognee`` auto-loads a project-root ``.env`` via
    python-dotenv as a side effect, which can pre-populate
    LLM_MODEL/LLM_PROVIDER/LLM_ENDPOINT/LLM_API_KEY in os.environ from a
    developer's real local config. Every test below explicitly clears
    all four before asserting on settings.json-derived values, so
    results don't depend on whichever machine/dev .env runs the suite.
    """

    _ENV_VARS = ("LLM_MODEL", "LLM_PROVIDER", "LLM_ENDPOINT", "LLM_API_KEY")

    def _clear_env(self, monkeypatch) -> None:
        for var in self._ENV_VARS:
            monkeypatch.delenv(var, raising=False)

    def _fake_acompletion(self):
        from unittest.mock import AsyncMock

        fake_response = type(
            "R",
            (),
            {"choices": [type("C", (), {"message": type("M", (), {"content": "ok"})()})()]},
        )()
        return AsyncMock(return_value=fake_response)

    def _write_cognee_settings(self, tmp_path, **cognee_cfg) -> None:
        import json as _json

        from deep_obsidian.settings import read_settings

        settings_path = tmp_path / ".deep-obsidian" / "settings.json"
        settings = read_settings(tmp_path)
        settings["backend"]["cognee"] = cognee_cfg
        settings_path.write_text(_json.dumps(settings))

    def test_custom_provider_omits_custom_llm_provider_kwarg(self, tmp_path, monkeypatch):
        """llm_provider=custom must NOT be forwarded as custom_llm_provider."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        self._clear_env(monkeypatch)
        init_project(tmp_path, name="routing-vault")
        self._write_cognee_settings(
            tmp_path,
            llm_model="openai/gpt-4o-mini",
            llm_provider="custom",
            llm_endpoint="https://custom.example.com/v1",
        )

        fake_acompletion = self._fake_acompletion()
        with (
            patch("deep_obsidian.query.litellm.acompletion", new=fake_acompletion),
            patch(
                "deep_obsidian.query.do_search",
                new=AsyncMock(return_value=[{"source_file": "a.md", "content": "hi"}]),
            ),
        ):
            asyncio.run(query("q", vault_path=str(tmp_path)))

        kwargs = fake_acompletion.call_args.kwargs
        assert kwargs["model"] == "openai/gpt-4o-mini"
        assert kwargs["api_base"] == "https://custom.example.com/v1"
        assert "custom_llm_provider" not in kwargs

    def test_non_custom_provider_is_forwarded(self, tmp_path, monkeypatch):
        """A real provider name (not "custom") IS forwarded to litellm."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        self._clear_env(monkeypatch)
        init_project(tmp_path, name="routing-vault-2")
        self._write_cognee_settings(tmp_path, llm_model="gpt-4o", llm_provider="openai")

        fake_acompletion = self._fake_acompletion()
        with (
            patch("deep_obsidian.query.litellm.acompletion", new=fake_acompletion),
            patch(
                "deep_obsidian.query.do_search",
                new=AsyncMock(return_value=[{"source_file": "a.md", "content": "hi"}]),
            ),
        ):
            asyncio.run(query("q", vault_path=str(tmp_path)))

        kwargs = fake_acompletion.call_args.kwargs
        assert kwargs["custom_llm_provider"] == "openai"

    def test_env_vars_override_settings_json_for_real_query_call(self, tmp_path, monkeypatch):
        """LLM_MODEL/LLM_API_KEY env vars must win over settings.json."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        self._clear_env(monkeypatch)
        init_project(tmp_path, name="routing-vault-3")
        self._write_cognee_settings(tmp_path, llm_model="settings-model", llm_api_key="sk-settings")

        monkeypatch.setenv("LLM_MODEL", "env-model")
        monkeypatch.setenv("LLM_API_KEY", "sk-env")

        fake_acompletion = self._fake_acompletion()
        with (
            patch("deep_obsidian.query.litellm.acompletion", new=fake_acompletion),
            patch(
                "deep_obsidian.query.do_search",
                new=AsyncMock(return_value=[{"source_file": "a.md", "content": "hi"}]),
            ),
        ):
            asyncio.run(query("q", vault_path=str(tmp_path)))

        kwargs = fake_acompletion.call_args.kwargs
        assert kwargs["model"] == "env-model"
        assert kwargs["api_key"] == "sk-env"


class TestQueryLockContention:
    """query() must gracefully degrade when the underlying search()
    exhausts its Ladybug lock retries — returning a friendly "retry
    later" answer instead of letting a raw RuntimeError bubble up to
    the CLI and confuse the user (P1 from test-coverage audit).
    """

    def test_query_returns_friendly_answer_when_search_lock_exhausted(
        self, tmp_path, mock_llm, monkeypatch
    ):
        """search() retries exhausted → query() catches the specific
        SearchLockContentionError and returns a helpful answer."""
        import asyncio

        from deep_obsidian.query import query
        from deep_obsidian.search import SearchLockContentionError
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="query-lock-test")

        async def _fake_search_lock_exhausted(
            query_text,
            dataset=None,
            vault_path=None,
            top_k=5,
            tag=None,
            linked_to=None,
            linked_from=None,
            date_from=None,
            date_to=None,
            source=None,
        ):
            raise SearchLockContentionError(
                "Search failed after retries: the knowledge graph "
                "is currently being written to (likely by a "
                "background sync). Please retry in a moment."
            )

        monkeypatch.setattr(
            "deep_obsidian.query.do_search",
            _fake_search_lock_exhausted,
        )

        result = asyncio.run(query("habits", vault_path=str(tmp_path)))

        assert isinstance(result, dict)
        assert "answer" in result
        assert "retry" in result["answer"].lower()
        assert result["sources"] == []

    def test_query_still_propagates_unrelated_errors(self, tmp_path, mock_llm, monkeypatch):
        """Non-lock errors (e.g. config, auth) must still propagate —
        only SearchLockContentionError is caught and turned into a
        friendly fallback."""
        import asyncio

        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A")
        init_project(tmp_path, name="query-nonlock-test")

        async def _fake_search_config_error(
            query_text,
            dataset=None,
            vault_path=None,
            top_k=5,
            tag=None,
            linked_to=None,
            linked_from=None,
            date_from=None,
            date_to=None,
            source=None,
        ):
            raise RuntimeError("Unrelated config error: bad API endpoint")

        monkeypatch.setattr(
            "deep_obsidian.query.do_search",
            _fake_search_config_error,
        )

        import pytest

        with pytest.raises(RuntimeError, match="Unrelated config error"):
            asyncio.run(query("habits", vault_path=str(tmp_path)))


class TestQueryLLMTransientFallback:
    """query()'s inline LLM call must gracefully degrade when litellm
    hits a transient error (timeout, connection failure, rate limit,
    service unavailable) — returning raw retrieval results instead of
    crashing.

    Regression: _fake_acompletion in the shared mock_llm fixture always
    returns success, so the ~20-line transient-exception fallback path
    in query.py:131-137 was never exercised by any test.
    """

    @pytest.mark.parametrize(
        "exception_class",
        [
            "APIConnectionError",
            "Timeout",
            "ServiceUnavailableError",
            "RateLimitError",
        ],
    )
    def test_llm_transient_error_returns_fallback_answer(
        self, tmp_path, mock_llm, monkeypatch, exception_class
    ):
        import asyncio

        from deep_obsidian.ingest import ingest
        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# Habits\n\nHabits are automatic behaviors.")
        init_project(tmp_path, name="llm-fallback-test")
        asyncio.run(ingest(str(tmp_path)))

        # litellm.exceptions 在函数内导入以避免模块级导入时的解析问题
        import litellm

        exc_cls = getattr(litellm.exceptions, exception_class)
        from unittest.mock import AsyncMock

        fake_acompletion = AsyncMock(
            side_effect=exc_cls(
                "simulated transient LLM error",
                llm_provider="openai",
                model="test-model",
            )
        )
        monkeypatch.setattr("deep_obsidian.query.litellm.acompletion", fake_acompletion)

        result = asyncio.run(query("habits", vault_path=str(tmp_path)))

        assert isinstance(result, dict)
        assert "answer" in result
        assert "LLM unavailable" in result["answer"]
        assert len(result["answer"]) > 0
        assert isinstance(result["sources"], list)

    def test_llm_permanent_error_still_propagates(self, tmp_path, mock_llm, monkeypatch):
        """Non-transient LLM errors (auth, bad model) must still propagate."""
        import asyncio

        from deep_obsidian.query import query
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# Test")
        init_project(tmp_path, name="llm-permanent-test")

        from deep_obsidian.ingest import ingest

        asyncio.run(ingest(str(tmp_path)))

        from unittest.mock import AsyncMock

        fake_acompletion = AsyncMock(side_effect=ValueError("invalid model name"))
        monkeypatch.setattr("deep_obsidian.query.litellm.acompletion", fake_acompletion)

        with pytest.raises(ValueError, match="invalid model name"):
            asyncio.run(query("test", vault_path=str(tmp_path)))
