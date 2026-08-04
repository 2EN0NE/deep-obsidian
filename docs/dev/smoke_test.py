"""
Cognee 极速通道验证：只摄入 3 篇
"""

import asyncio
import os
import time

import cognee

VAULT = os.path.join(os.path.dirname(__file__), "obsidian-test")
DS = "smoke_test"

md_files = []
for root, dirs, files in os.walk(VAULT):
    dirs[:] = [d for d in dirs if not d.startswith(".")]
    for f in files:
        if f.endswith(".md"):
            md_files.append(os.path.join(root, f))
md_files = md_files[:3]

print(f"烟雾测试: {len(md_files)} 篇")
for f in md_files:
    print(f"  - {os.path.relpath(f, VAULT)}")


async def main():
    t0 = time.time()
    for i, f in enumerate(md_files):
        rel = os.path.relpath(f, VAULT)
        t1 = time.time()
        try:
            await cognee.remember(f, dataset_name=DS)
            print(f"  [{i + 1}] ✅ {rel} ({time.time() - t1:.1f}s)")
        except Exception as e:
            print(f"  [{i + 1}] ❌ {rel}: {e}")

    print(f"\n摄入耗时: {time.time() - t0:.1f}s")

    # 简单召回
    query = "这些文章讲了什么？"
    print(f"\n召回测试: {query}")
    try:
        results = await cognee.recall(query_text=query, datasets=[DS])
        for j, r in enumerate(results[:3]):
            text = (getattr(r, "text", "") or str(r))[:150]
            print(f"  [{j + 1}] {text}")
    except Exception as e:
        print(f"  召回失败: {e}")

    print("\n烟雾测试完毕 ✅")


asyncio.run(main())
