"""
Cognee 全量导入 Obsidian Vault
支持断点续跑（已导入的文件自动跳过）
"""

import asyncio
import json
import os
import signal
import time

import cognee

VAULT = os.path.join(os.path.dirname(__file__), "obsidian-test")
DATASET = "obsidian_full"
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), ".ingest_progress.json")

# ── 锁清理 ──
LADYBUG_DB = os.path.expanduser(
    os.path.join(
        os.path.dirname(cognee.__file__),
        ".cognee_system/databases/cognee_graph_ladybug",
    )
)


def clear_lock():
    lock_file = os.path.join(LADYBUG_DB, "LOCK")
    if not os.path.exists(lock_file):
        return
    try:
        with open(lock_file) as f:
            content = f.read().strip()
            pid = int(content) if content.isdigit() else None
    except Exception:
        pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        os.remove(lock_file)
        print("  ✅ 已清除残留锁\n")
    except OSError:
        pass


def collect_files(vault: str) -> list[str]:
    files = []
    for root, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "attachments"]
        for f in fs:
            if f.endswith(".md"):
                files.append(os.path.join(root, f))
    return sorted(files)


def load_progress() -> set[str]:
    try:
        with open(PROGRESS_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_progress(done: set[str]):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(sorted(done), f)


async def main():
    clear_lock()

    files = collect_files(VAULT)
    done = load_progress()
    remaining = [f for f in files if os.path.basename(f) not in done]

    print(f"共 {len(files)} 篇, 已完成 {len(done)} 篇, 剩余 {len(remaining)} 篇\n")

    if not remaining:
        print("全部已完成！")
    else:
        print(f"预计总耗时: ~{len(remaining) * 2 / 60:.0f} 分钟 (每篇约 2 分钟)")

    success, failed = 0, []
    t_start = time.time()

    for i, fpath in enumerate(remaining):
        rel = os.path.relpath(fpath, VAULT)
        fname = os.path.basename(fpath)
        t1 = time.time()
        try:
            await cognee.remember(fpath, dataset_name=DATASET)
            elapsed = time.time() - t1
            success += 1
            done.add(fname)
            save_progress(done)

            avg = (time.time() - t_start) / success if success > 0 else 120
            eta_min = (len(remaining) - i - 1) * avg / 60
            print(
                f"  [{i + 1:2d}/{len(remaining)}] ✅ {rel[:50]:50s} "
                f"{elapsed:5.0f}s  ETA {eta_min:.0f}min"
            )
        except Exception as e:
            failed.append((rel, str(e)[:120]))
            print(f"  [{i + 1:2d}/{len(remaining)}] ❌ {rel[:50]:50s} {str(e)[:80]}")

    total_t = time.time() - t_start
    print(f"\n{'─' * 60}")
    print(f"导入完成: {len(done)}/{len(files)} 成功, 耗时 {total_t / 60:.1f}min")
    if failed:
        print(f"失败 {len(failed)} 篇:")
        for name, err in failed:
            print(f"  - {name}: {err}")

    # 召回验证
    print("\n召回验证: 这些文章涵盖哪些核心主题？")
    try:
        results = await cognee.recall(
            query_text="这些文章涵盖哪些核心主题？试着分类总结。",
            datasets=[DATASET],
            top_k=3,
        )
        for r in results:
            text = getattr(r, "text", "") or str(r)
            if text:
                print(f"  {text[:300]}")
    except Exception as e:
        print(f"  召回失败: {e}")

    print(f"\n全量导入完毕! dataset='{DATASET}'")


asyncio.run(main())
