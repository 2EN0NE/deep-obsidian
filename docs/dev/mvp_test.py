"""
Cognee + Obsidian Markdown MVP 验证脚本
测试维度：摄入成功率、召回质量、来源追溯
"""

import asyncio
import os
import time

import cognee
from cognee.infrastructure.databases.vector.embeddings.config import (
    get_embedding_config,
)
from cognee.infrastructure.llm.config import get_llm_config

# 配置
VAULT_PATH = os.path.join(os.path.dirname(__file__), "obsidian-test")
DATASET = "obsidian_mvp"


def collect_md_files(vault_path: str, limit: int = 20) -> list[str]:
    """收集 Obsidian vault 中的 markdown 文件"""
    md_files = []
    for root, dirs, files in os.walk(vault_path):
        # 跳过 .obsidian 等隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))
    return md_files[:limit]


async def step1_config_check():
    """步骤 0：验证配置加载"""
    print("=" * 60)
    print("步骤 0：验证配置加载")
    print("=" * 60)
    llm = get_llm_config()
    emb = get_embedding_config()
    print(f"  LLM Provider:   {llm.llm_provider}")
    print(f"  LLM Model:      {llm.llm_model}")
    print(f"  LLM Endpoint:   {llm.llm_endpoint}")
    print(f"  Emb Provider:   {emb.embedding_provider}")
    print(f"  Emb Model:      {emb.embedding_model}")
    print(f"  Emb Dimensions: {emb.embedding_dimensions}")
    print()


async def step2_ingest(md_files: list[str]):
    """步骤 1：摄入文章"""
    print("=" * 60)
    print(f"步骤 1：摄入 {len(md_files)} 篇文章")
    print("=" * 60)

    success = 0
    failed = []
    total_start = time.time()

    for i, f in enumerate(md_files):
        rel = os.path.relpath(f, VAULT_PATH)
        file_start = time.time()
        try:
            await cognee.remember(f, dataset_name=DATASET)
            elapsed = time.time() - file_start
            success += 1
            print(f"  [{i + 1:2d}/{len(md_files)}] ✅ {rel} ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - file_start
            failed.append((rel, str(e)))
            print(f"  [{i + 1:2d}/{len(md_files)}] ❌ {rel} ({elapsed:.1f}s): {e}")

    total_elapsed = time.time() - total_start
    print(
        f"\n摄入完成: {success}/{len(md_files)} 成功, "
        f"总耗时 {total_elapsed:.0f}s, "
        f"平均 {total_elapsed / success:.1f}s/篇"
        if success > 0
        else ""
    )

    return {"success": success, "failed": failed, "total": len(md_files)}


async def step3_recall():
    """步骤 2：测试召回"""
    print("\n" + "=" * 60)
    print("步骤 2：测试召回质量")
    print("=" * 60)

    test_queries = [
        "如何养成良好的习惯？",
        "投资中最重要的事是什么？",
        "关于谈判技巧有哪些建议？",
        "如何理解系统思维？",
    ]

    for query in test_queries:
        print(f"\n🔍 问题: {query}")
        try:
            results = await cognee.recall(query_text=query, datasets=[DATASET])
            if results:
                for j, r in enumerate(results[:3]):
                    source = getattr(r, "source", "未知来源")
                    text = (getattr(r, "text", "") or str(r))[:120]
                    print(f"    [{j + 1}] 📄 {source}")
                    print(f"        {text}...")
            else:
                print("    （无结果）")
        except Exception as e:
            print(f"    ❌ 召回失败: {e}")


async def main():
    md_files = collect_md_files(VAULT_PATH, limit=20)
    print(f"在 {VAULT_PATH} 中发现 {len(md_files)} 篇可用于测试的文章\n")

    await step1_config_check()
    ingest_result = await step2_ingest(md_files)
    await step3_recall()

    print("\n" + "=" * 60)
    print("MVP 验证完毕")
    print("=" * 60)
    print(f"摄入: {ingest_result['success']}/{ingest_result['total']} 成功")
    if ingest_result["failed"]:
        print(f"失败: {len(ingest_result['failed'])} 篇")
        for fname, err in ingest_result["failed"]:
            print(f"  - {fname}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
