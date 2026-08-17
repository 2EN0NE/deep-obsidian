"""Shared e2e fixtures — user-level base config (ADR-0014).

resolve_config() requires the user-level layer (~/.deep-obsidian/settings.jsonc)
to exist.  This autouse fixture points HOME at a temp dir with a user-level
config so every e2e test resolves cleanly without editing each test.
"""

from __future__ import annotations

import pytest

from deep_obsidian.settings import init_project


@pytest.fixture(autouse=True)
def user_level(tmp_path, monkeypatch):
    """Create a user-level config (required merge base layer)."""
    home = tmp_path / "user-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    init_project(home, name="user", level="user")
    return home
