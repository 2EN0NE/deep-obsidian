"""Root test fixtures — available to all test subdirectories."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_llm():
    """Replace cognee API calls with no-LLM stubs.

    Mocks add / cognify / update / forget / recall / acompletion so
    that tests run without a real LLM backend.
    """

    _dataset_id = str(uuid.uuid4())
    _dataset_names: set[str] = set()

    async def _fake_add(data, dataset_name=None, **kwargs):
        if dataset_name:
            _dataset_names.add(dataset_name)
        return type("RunInfo", (), {"dataset_id": _dataset_id, "status": "completed"})()

    async def _fake_cognify(datasets=None, **kwargs):
        return type("RunInfo", (), {"status": "completed"})()

    async def _fake_list_datasets():
        return [type("FakeDataset", (), {"name": n, "id": f"fake-{n}"})() for n in _dataset_names]

    async def _fake_update(data_id, data, dataset_id, **kwargs):
        return type("RunInfo", (), {"status": "completed"})()

    async def _fake_forget(
        *,
        data_id=None,
        dataset=None,
        dataset_id=None,
        everything=False,
        memory_only=False,
        user=None,
    ):
        # Mirrors cognee.forget()'s real signature exactly (it has no
        # **kwargs catch-all) so a call site that passes a wrong keyword
        # name (e.g. dataset_name instead of dataset) fails the test with
        # a TypeError, the same way it would against the real API.
        return None

    async def _fake_recall(query_text=None, datasets=None, top_k=5, only_context=False, **kwargs):
        return [
            type(
                "RecallResult",
                (),
                {
                    "text": "Habits are automatic behaviors. [[cue]] [[reward]]",
                    "label": "habit",
                    "kind": "document",
                    "source": "habit.md",
                    "tags": ["habit", "psychology"],
                },
            )(),
            type(
                "RecallResult",
                (),
                {
                    "text": "A cue triggers [[habit|the habit loop]].",
                    "label": "cue",
                    "kind": "document",
                    "source": "cue.md",
                    "tags": ["habit"],
                },
            )(),
        ]

    async def _fake_acompletion(
        model=None,
        messages=None,
        max_tokens=None,
        api_base=None,
        custom_llm_provider=None,
        **kwargs,
    ):
        return type(
            "Completion",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Msg",
                                (),
                                {"content": "Based on your notes, habits are automatic."},
                            )()
                        },
                    )()
                ]
            },
        )()

    async def _fake_resolve(_dataset_name):
        return _dataset_id

    with (
        patch("cognee.add", new=_fake_add),
        patch("cognee.api.v1.add.add", new=_fake_add),
        patch("cognee.cognify", new=_fake_cognify),
        patch("cognee.api.v1.cognify.cognify", new=_fake_cognify),
        patch("cognee.update", new=_fake_update),
        patch("cognee.api.v1.update.update", new=_fake_update),
        patch("cognee.forget", new=_fake_forget),
        patch("cognee.api.v1.forget.forget", new=_fake_forget),
        patch("cognee.recall", new=_fake_recall),
        patch("cognee.api.v1.recall.recall.recall", new=_fake_recall),
        patch("litellm.acompletion", new=_fake_acompletion),
        patch("deep_obsidian.ingest._resolve_dataset_id", new=_fake_resolve),
        patch("cognee.datasets.list_datasets", new=_fake_list_datasets),
    ):
        yield


@pytest.fixture
def mock_llm_degraded():
    """Like mock_llm, but add() raises _LLMDegradedWarning.

    Use to verify that the ingest pipeline handles LLM unavailability
    gracefully — structural data is preserved, warnings are recorded.
    """

    _dataset_names: set[str] = set()

    async def _fake_add_degraded(data, dataset_name=None, **kwargs):
        from deep_obsidian.ingest import _LLMDegradedWarning

        if dataset_name:
            _dataset_names.add(dataset_name)
        raise _LLMDegradedWarning("LLM unavailable (simulated)")

    async def _fake_cognify(datasets=None, **kwargs):
        return type("RunInfo", (), {"status": "completed"})()

    async def _fake_list_datasets():
        return [type("FakeDataset", (), {"name": n, "id": f"fake-{n}"})() for n in _dataset_names]

    async def _fake_forget(
        *,
        data_id=None,
        dataset=None,
        dataset_id=None,
        everything=False,
        memory_only=False,
        user=None,
    ):
        # See mock_llm's _fake_forget for why there's no **kwargs here.
        return None

    with (
        patch("cognee.add", new=_fake_add_degraded),
        patch("cognee.api.v1.add.add", new=_fake_add_degraded),
        patch("cognee.cognify", new=_fake_cognify),
        patch("cognee.api.v1.cognify.cognify", new=_fake_cognify),
        patch("cognee.forget", new=_fake_forget),
        patch("cognee.api.v1.forget.forget", new=_fake_forget),
        patch("cognee.datasets.list_datasets", new=_fake_list_datasets),
    ):
        yield
