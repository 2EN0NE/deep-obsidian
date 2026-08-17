"""Tests for user-level vault registry — ~/.deep-obsidian/vaults/index.json (ADR-0014)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_obsidian.settings import (
    load_vault_index,
    register_vault,
    unregister_vault,
    vault_path_hash,
)

VAULT_A = Path("/vaults/alpha")
VAULT_B = Path("/vaults/beta")


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    d = tmp_path / "home" / ".deep-obsidian"
    d.mkdir(parents=True)
    return d


class TestVaultIndex:
    """index.json 读写与映射维护。"""

    def test_missing_index_returns_empty(self, user_dir: Path):
        assert load_vault_index(user_dir) == {}

    def test_register_creates_index(self, user_dir: Path):
        register_vault(user_dir, VAULT_A, dataset="alpha")
        idx = load_vault_index(user_dir)
        h = vault_path_hash(VAULT_A)
        assert h in idx
        assert idx[h]["vault_path"] == str(VAULT_A.resolve())
        assert idx[h]["dataset"] == "alpha"
        assert "updated_at" in idx[h]

    def test_register_multiple_vaults(self, user_dir: Path):
        register_vault(user_dir, VAULT_A, dataset="alpha")
        register_vault(user_dir, VAULT_B, dataset="beta")
        idx = load_vault_index(user_dir)
        assert set(idx.keys()) == {vault_path_hash(VAULT_A), vault_path_hash(VAULT_B)}

    def test_register_overwrites_same_vault(self, user_dir: Path):
        register_vault(user_dir, VAULT_A, dataset="alpha")
        register_vault(user_dir, VAULT_A, dataset="alpha-renamed")
        idx = load_vault_index(user_dir)
        assert len(idx) == 1
        assert idx[vault_path_hash(VAULT_A)]["dataset"] == "alpha-renamed"

    def test_unregister_removes_entry(self, user_dir: Path):
        register_vault(user_dir, VAULT_A, dataset="alpha")
        register_vault(user_dir, VAULT_B, dataset="beta")
        unregister_vault(user_dir, VAULT_A)
        idx = load_vault_index(user_dir)
        assert vault_path_hash(VAULT_A) not in idx
        assert vault_path_hash(VAULT_B) in idx

    def test_unregister_missing_is_noop(self, user_dir: Path):
        unregister_vault(user_dir, VAULT_A)
        assert load_vault_index(user_dir) == {}

    def test_index_file_path(self, user_dir: Path):
        assert not (user_dir / "vaults" / "index.json").is_file()
        register_vault(user_dir, VAULT_A, dataset="a")
        assert (user_dir / "vaults" / "index.json").is_file()
