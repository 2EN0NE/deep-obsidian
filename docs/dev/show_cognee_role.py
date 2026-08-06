"""
展示 Cognee 的完整工作链路：
  ① 检索出什么原始内容
  ② 转换后发给 LLM 的问题（上下文 + 提问）
  ③ LLM 生成的最终答案
"""

import asyncio

import cognee

DS = "obsidian_5"

QUERY = "如何养成良好的习惯？"


async def inspect():
    # ─── 第一步：检索原始内容 ───
    print("=" * 60)
    print("① Cognee 从知识图谱中检索到的原始内容")
    print("=" * 60)
    raw_context = await cognee.recall(
        query_text=QUERY,
        datasets=[DS],
        only_context=True,
        top_k=5,
    )

    chunks = []
    for i, r in enumerate(raw_context):
        text = getattr(r, "text", "") or str(r)
        # 清理内部标记
        clean = (
            text.replace("__node_content_start__", "").replace("__node_content_end__", "").strip()
        )
        chunks.append(clean[:800])
        print(f"\n  📄 片段 {i + 1}:")
        for line in clean[:800].split("\n"):  # pyright: ignore[reportUnknownVariableType]
            print(f"      │ {line}"[:120])

    # ─── 第二步：展示发给 LLM 的提示词 ───
    print("\n" + "=" * 60)
    print("② 发给大模型的提示词（重构版）")
    print("=" * 60)
    print("""
  ┌─ System Prompt ─────────────────────────────────┐
  │ 你是一个知识助手。根据以下上下文回答问题。       │
  │ 如果上下文不足，如实说不知道。                     │
  │ 请基于以下来自知识库的检索结果回答用户问题。       │
  └──────────────────────────────────────────────────┘

  ┌─ Context（Cognee 从图+向量检索到的上下文）───────""")

    for i, c in enumerate(chunks):
        preview = c[:200].replace("\n", " ").strip()
        print(f"  │ [{i + 1}] {preview}...")

    print(f"""  └──────────────────────────────────────────────────┘

  ┌─ User Query ─────────────────────────────────────┐
  │ {QUERY}
  └──────────────────────────────────────────────────┘
""")

    # ─── 第三步：LLM 的最终答案 ───
    print("=" * 60)
    print("③ 大模型基于以上内容生成的答案")
    print("=" * 60)

    result = await cognee.recall(query_text=QUERY, datasets=[DS], top_k=3)
    for i, r in enumerate(result):
        text = getattr(r, "text", "") or str(r)
        src = getattr(r, "source", "?")
        print(f"\n  📎 来源: {src}")
        print("  ────────────────────────────────────────────────")
        for line in text[:600].split("\n"):
            print(f"     {line}"[:120])

    print()


asyncio.run(inspect())
