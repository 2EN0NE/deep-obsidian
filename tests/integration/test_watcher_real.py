"""真实 watchfiles 事件循环的冒烟集成测试（不 mock awatch）。

unit 层（tests/unit/test_watcher.py）全部用 fake_awatch 模拟事件流，
watchfiles 的真实事件语义（Change 枚举、FSEvents/inotify 传播、debounce）
从未被验证——mock 里硬编码的 Change.modified=2/Change.deleted=3 若在
watchfiles 升级后变化，测试会静默错判。

这里用真实 awatch 验证最小链路：文件修改 → on_event 收到
("a.md", "modified")。事件时序不可控（FSEvents/inotify 有传播延迟），
用 deadline 轮询而非固定 sleep（与 test_service.py 的既有风格一致）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deep_obsidian.settings import init_project

pytestmark = pytest.mark.integration

_DEADLINE_SECONDS = 15


@pytest.mark.asyncio
async def test_real_watchfiles_dispatches_modified(tmp_path: Path) -> None:
    """真实 awatch 下修改 .md 文件，on_event 必须收到 modified 事件。"""
    from deep_obsidian.service._watcher import watch

    init_project(tmp_path, name="real-watch")
    note = tmp_path / "a.md"
    note.write_text("# A\n\nv1")
    hashes_path = tmp_path / ".deep-obsidian" / "vault" / "hashes.json"

    # 模拟 service 启动时的初始入库（真实链路中 run_service 先做 initial
    # ingest，hashes.json 记录每个文件的 hash）。macOS FSEvents 对覆盖写入
    # 常报 Change.added 而非 modified——_handle 的 created 分支依赖
    # "rel in stored" 才能把它补偿为 modified。不预置该状态会得到两条
    # created（初始快照 + 修改），modified 永远不来。
    from deep_obsidian.ingest._fingerprint import file_hash, save_hashes

    save_hashes(str(hashes_path), {"a.md": {"hash": file_hash(str(note))}})

    events: list[tuple[str, str]] = []
    shutdown = asyncio.Event()

    async def on_event(rel: str, event_type: str) -> None:
        events.append((rel, event_type))

    task = asyncio.create_task(watch(tmp_path, hashes_path, shutdown, on_event))
    try:
        # 给 watcher 一点启动时间（awatch 首轮扫描 + 事件循环就绪）
        await asyncio.sleep(1.0)
        note.write_text("# A\n\nv2 content changed")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _DEADLINE_SECONDS
        while loop.time() < deadline and not any(
            rel == "a.md" and etype == "modified" for rel, etype in events
        ):
            await asyncio.sleep(0.1)

        assert ("a.md", "modified") in events, (
            f"真实 awatch 未派发 modified 事件（{_DEADLINE_SECONDS}s 内）: {events}"
        )
    finally:
        shutdown.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
