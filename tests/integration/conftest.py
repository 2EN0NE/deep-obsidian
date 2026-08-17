"""Integration test fixtures — realistic Obsidian vaults.

The ``mock_llm`` and ``mock_llm_degraded`` fixtures are defined in
the root ``tests/conftest.py`` and auto-discovered by pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ── Vault fixtures ──


@pytest.fixture(autouse=True)
def _user_level_base(tmp_path: Path, monkeypatch) -> None:
    """ADR-0014：用户级是必需基础层——所有 ingest/forget/service 入口都先
    resolve_config()，缺失 ~/.deep-obsidian/settings.jsonc 会直接报错。
    把 HOME 隔离到临时目录并兼建用户级配置，避免读到真实机器上的配置。
    """
    from deep_obsidian.settings import init_project

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    init_project(home, name="user-base", level="user")


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Empty temp vault directory, already initialized."""
    from deep_obsidian.settings import init_project

    init_project(tmp_path, name="tmp-vault")
    return tmp_path


@pytest.fixture
def simple_vault(tmp_path: Path) -> Path:
    """Vault with 2 simple markdown files, no wikilinks."""
    from deep_obsidian.settings import init_project

    root = tmp_path
    init_project(root, name="simple-vault")
    (root / "note1.md").write_text("""---
title: First Note
tags: [habit, psychology]
---
# First Note

This note discusses habits and how they form.

Habits are mental shortcuts learned from experience.
They consist of cue, craving, response, and reward.
""")
    (root / "note2.md").write_text("""---
title: Second Note
tags: [learning]
---
# Second Note

Learning how to study effectively is important.

Spaced repetition and active recall are two key techniques.
""")
    return root


@pytest.fixture
def wikilink_vault(tmp_path: Path) -> Path:
    """Vault with wikilinks and frontmatter."""
    from deep_obsidian.settings import init_project

    root = tmp_path
    init_project(root, name="wikilink-vault")
    (root / "habit.md").write_text("""---
tags: [habit, psychology]
aliases: [习惯]
---
# 习惯

See also [[cue]] and [[reward]].

习惯是从经验中学到的心理捷径。
""")
    (root / "cue.md").write_text("""---
tags: [habit]
---
# Cue

A cue triggers [[habit|the habit loop]].

提示触发你的大脑启动某种行为举止。
""")
    (root / "reward.md").write_text("""---
tags: [habit]
---
# Reward

The reward completes [[habit#four steps|the loop]].

奖励是养成每个习惯的最终目标。
""")
    return root


@pytest.fixture
def long_vault(tmp_path: Path) -> Path:
    """Vault with one long multi-section note (~5k chars)."""
    from deep_obsidian.settings import init_project

    root = tmp_path
    init_project(root, name="long-vault")
    sections = []
    for i in range(1, 11):
        sections.append(f"### 第{i}章\n\n{'这是测试内容。' * 50}\n")
    full_body = "\n\n".join(sections)
    text = f"---\ntags: [test]\n---\n\n# 长笔记测试\n\n{full_body}\n\n相关: [[cue]] [[reward]]"
    (root / "long_note.md").write_text(text)
    return root
