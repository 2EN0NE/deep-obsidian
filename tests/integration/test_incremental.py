"""Tests for incremental ingest (fingerprint-based skip)."""


class TestIncrementalIngest:
    def test_second_ingest_skips_unchanged(self, tmp_path, mock_llm):
        """第二次 ingest 跳过未变化的文件"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Original\n\nContent here.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 1
        assert r1["unchanged"] == 0

        # Second ingest — no changes
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["unchanged"] == 1
        assert r2["added"] == 0

    def test_modified_file_re_ingested(self, tmp_path, mock_llm):
        """修改后的文件会被重新 ingest"""
        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        note = tmp_path / "note.md"
        note.write_text("# Original\n\nOld content.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 1

        # Modify the file
        note.write_text("# Modified\n\nNew content here.")

        # Second ingest — should re-ingest as modified
        r2 = asyncio.run(ingest(str(tmp_path)))
        assert r2["modified"] == 1
        assert r2["unchanged"] == 0

    def test_full_flag_reprocesses_via_update_not_add(self, tmp_path, mock_llm):
        """--full 强制重新处理已入库文件，但走 update() 而非 add()。

        Regression: --full 曾经丢弃 stored_hashes，把所有已入库文件当
        "新文件"重新 add()，生成一个全新的 data_id —— 在 Cognee 图谱里对
        同一份内容产生两个不同 data_id 的重复节点（ADR-0005 明确要杜绝
        的 bug class）。修复后已入库文件在 --full 下走 update()（复用旧
        data_id），只有真正的新文件才走 add()。
        """
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "note.md").write_text("# Test\n\nContent.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        # First ingest
        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 1

        hashes_path = str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json")
        data_id_before = load_hashes(hashes_path)["note.md"]["data_id"]

        # Second ingest with full=True — reprocesses despite unchanged content,
        # but as "modified" (update), not "added" (add) — no duplicate node.
        r2 = asyncio.run(ingest(str(tmp_path), full=True))
        assert r2["modified"] == 1
        assert r2["added"] == 0
        assert r2["unchanged"] == 0

        # The data_id must be preserved across the --full re-ingest — a
        # changed data_id would mean the file got a second, duplicate
        # entry in Cognee's graph instead of updating the existing one.
        data_id_after = load_hashes(hashes_path)["note.md"]["data_id"]
        assert data_id_after == data_id_before

    def test_full_flag_still_adds_new_and_deletes_removed_files(self, tmp_path, mock_llm):
        """--full 下新文件仍走 add()，被删除的文件仍被检测并清理。

        Regression: 丢弃 stored_hashes 的旧实现会让 --full 模式下
        deleted_rels 恒为空集合 —— 被删除的文件永远不会被清理。
        """
        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "keep.md").write_text("# Keep\n\nContent.")
        (tmp_path / "gone.md").write_text("# Gone\n\nWill be deleted.")
        init_project(tmp_path, name="test-vault")

        import asyncio

        r1 = asyncio.run(ingest(str(tmp_path)))
        assert r1["added"] == 2

        (tmp_path / "gone.md").unlink()
        (tmp_path / "new.md").write_text("# New\n\nBrand new.")

        r2 = asyncio.run(ingest(str(tmp_path), full=True))
        assert r2["added"] == 1  # new.md
        assert r2["modified"] == 1  # keep.md, reprocessed via update()
        assert r2["deleted"] == 1  # gone.md, still detected and cleaned up

        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json"))
        assert "gone.md" not in hashes
        assert "keep.md" in hashes
        assert "new.md" in hashes


class TestLegacyV1HashesUpgrade:
    """hashes.json v1 格式（entry 有 hash 无 data_id）的升级路径。

    ingest/__init__.py:273 的 "No data_id — treat as add (old format
    upgrade path)" 分支此前只在 save 函数层（test_fingerprint）测过，
    没有集成用例触发 ingest() 内的真实升级：v1 文件被修改后走 update
    分支、发现缺 data_id、回退到 add() 并补写 data_id。
    """

    def _v1_hashes(self, tmp_path, rel: str):
        """构造 v1 格式 hashes.json（{rel: {"hash": ...}}，无 data_id）。"""
        from deep_obsidian.ingest._fingerprint import file_hash, save_hashes

        save_hashes(
            str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json"),
            {rel: {"hash": file_hash(str(tmp_path / rel))}},
        )

    def test_unchanged_v1_file_still_skipped(self, tmp_path, mock_llm):
        """v1 格式下未修改的文件第二次 ingest 仍按 hash 跳过（不重复入库）。"""
        import asyncio

        from deep_obsidian.ingest import ingest
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A\n\nContent A.")
        init_project(tmp_path, name="v1-skip")
        asyncio.run(ingest(str(tmp_path)))

        # 降级为 v1 格式（模拟旧版本遗留的 hashes.json）
        self._v1_hashes(tmp_path, "a.md")
        r = asyncio.run(ingest(str(tmp_path)))
        assert r["unchanged"] == 1
        assert r["added"] == 0
        assert r["modified"] == 0

    def test_modified_v1_file_upgrades_with_data_id(self, tmp_path, mock_llm):
        """v1 文件被修改 → update 分支发现无 data_id → 回退 add() 并升级为 v2。

        Regression：该升级路径若误复用/丢弃 data_id，会在 Cognee 图谱产生
        重复节点（ADR-0005 的 bug class）。断言：added==1（不是 modified，
        因为旧 entry 无 data_id 无从 update），且升级后 entry 含 data_id。
        """
        import asyncio

        from deep_obsidian.ingest import ingest
        from deep_obsidian.ingest._fingerprint import load_hashes
        from deep_obsidian.settings import init_project

        (tmp_path / "a.md").write_text("# A\n\nContent A.")
        init_project(tmp_path, name="v1-upgrade")
        asyncio.run(ingest(str(tmp_path)))

        # 降级为 v1 格式，然后修改文件内容 → 触发 update 分支的升级路径
        self._v1_hashes(tmp_path, "a.md")
        (tmp_path / "a.md").write_text("# A\n\nUpdated content.")

        r = asyncio.run(ingest(str(tmp_path)))
        assert r["added"] == 1, f"expected fallback-to-add upgrade, got {r}"
        assert r["modified"] == 0
        assert r["failed"] == 0

        # 升级后 entry 必须带 data_id（v2 格式）
        hashes = load_hashes(str(tmp_path / ".deep-obsidian" / "vault" / "hashes.json"))
        assert hashes["a.md"].get("data_id"), f"a.md 未升级为 v2: {hashes['a.md']}"
        # hash 反映新内容
        from deep_obsidian.ingest._fingerprint import file_hash

        assert hashes["a.md"]["hash"] == file_hash(str(tmp_path / "a.md"))
