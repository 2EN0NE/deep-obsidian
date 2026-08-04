"""
精选 5 篇代表文章快速构建，验证图谱 + 召回
"""

import asyncio
import os
import time

import cognee

VAULT = os.path.join(os.path.dirname(__file__), "obsidian-test")
DS = "obsidian_5"

# 精选 5 篇覆盖不同领域
PICKS = [
    "Books/《掌控习惯》.md",
    "Books/《投资最重要的事》.md",
    "Books/《哈佛经典谈判术》.md",
    "Books/《系统之美》.md",
    "9.榜样的认知.md",
]


async def main():
    print("精选 5 篇，覆盖习惯/投资/谈判/系统思维/认知...\n")
    t0 = time.time()

    for i, rel in enumerate(PICKS):
        fpath = os.path.join(VAULT, rel)
        t1 = time.time()
        try:
            await cognee.remember(fpath, dataset_name=DS)
            print(f"  [{i + 1}/5] ✅ {rel} ({time.time() - t1:.1f}s)")
        except Exception as e:
            print(f"  [{i + 1}/5] ❌ {rel}: {e}")

    print(f"\n总耗时: {(time.time() - t0) / 60:.1f}min\n")

    # 召回测试
    queries = [
        "如何养成良好的习惯？",
        "投资中最重要的是什么？",
        "谈判的核心技巧有哪些？",
        "什么是系统思维？",
    ]
    for q in queries:
        print(f"🔍 {q}")
        try:
            results = await cognee.recall(query_text=q, datasets=[DS], top_k=2)
            for r in results:
                text = (getattr(r, "text", "") or str(r))[:150]
                print(f"   > {text}")
        except Exception as e:
            print(f"   ❌ {e}")
        print()

    # 可视化
    print("保存图谱可视化...")
    try:
        await cognee.visualize_graph()
        print("  ✅ 交互式 HTML 已保存（查看 /tmp/cognee_graph*.html）")
    except Exception as e:
        print(f"  ⚠️ 可视化失败: {e}")

    print("\n完成！dataset='obsidian_5'")


asyncio.run(main())
