r"""
Cognee 交互查询终端 —— 一站式展示完整管线：
  ① 检索到的知识片段及来源文章
  ② 发给大模型的提示词
  ③ 大模型的回答

用法：
  ENABLE_BACKEND_ACCESS_CONTROL=false COGNEE_SKIP_CONNECTION_TEST=true python query.py
  输入问题回车，quit 退出
"""

import asyncio
import os
import re
import signal

import cognee

DS = "obsidian_5"

# ── 启动自检 ──
LADYBUG_DB = os.path.expanduser(
    os.path.join(
        os.path.dirname(cognee.__file__),
        ".cognee_system/databases/cognee_graph_ladybug",
    )
)


def _check_and_clear_lock():
    """检测并清理 Ladybug 图数据库残留锁"""
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
            os.kill(pid, 0)  # 检测进程是否存在
            print(f"  ⚠️  发现残留进程 PID={pid}，正在清理...")
            os.kill(pid, signal.SIGKILL)
            print(f"  ✅ 已终止 PID={pid}")
        except OSError:
            pass  # 进程不存在

    # 删除锁文件
    try:
        os.remove(lock_file)
        print("  ✅ 已清除图数据库锁文件")
    except OSError:
        pass


def _check_env():
    """检查运行环境"""
    issues = []
    if os.environ.get("ENABLE_BACKEND_ACCESS_CONTROL") not in ("false", "0", ""):
        issues.append("⚠️  建议设置 ENABLE_BACKEND_ACCESS_CONTROL=false")

    if os.environ.get("HF_ENDPOINT") != "https://hf-mirror.com":
        issues.append("⚠️  建议设置 HF_ENDPOINT=https://hf-mirror.com")

    return issues


# ── 内容提取 ──


def extract_content(r) -> str:
    """从 Cognee 响应对象中提取真实文本内容"""
    # .text 字段
    text = getattr(r, "text", None)
    if text and isinstance(text, str) and len(text.strip()) > 10:
        return text

    # .raw.value 字段
    raw = getattr(r, "raw", None)
    if isinstance(raw, dict):
        value = raw.get("value", "")
        if value and isinstance(value, str) and len(value) > 10:
            return value

    return ""


def clean_and_split_nodes(raw_text: str) -> list[dict]:
    """把 Cognee 'Nodes:\nNode: ...' 格式拆成清晰条目"""
    if not raw_text.strip():
        return []

    entries = []
    text = re.sub(r"^Nodes:\s*\n*", "", raw_text.strip())

    blocks = re.split(r"__node_content_start__", text)
    for block in blocks:
        parts = block.split("__node_content_end__", 1)
        content = parts[0].strip()

        label_m = re.search(r"^Node:\s*(.+)$", content, re.MULTILINE)
        label = label_m.group(1).strip() if label_m else ""

        pure = re.sub(r"^Node:\s*.+$", "", content, flags=re.MULTILINE).strip()
        if pure:
            entries.append({"label": label, "content": pure})
    return entries


def extract_book(label: str, content: str) -> str:
    """从标签或内容中提取书名"""
    m = re.search(r"《([^》]+)》", label + "\n" + content[:200])
    if m:
        return m.group(1)
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "(未识别)"


# ── 核心查询 ──


async def ask(question: str):
    # ── ① 检索 ──
    ctx = await cognee.recall(query_text=question, datasets=[DS], only_context=True, top_k=5)

    all_entries = []
    for r in ctx:
        raw = extract_content(r)
        entries = clean_and_split_nodes(raw)
        all_entries.extend(entries)

    print(f"\n{'─' * 60}")
    print(f"① 知识图谱检索结果（共 {len(all_entries)} 个实体/片段）")
    print(f"{'─' * 60}")

    if all_entries:
        for i, e in enumerate(all_entries[:15]):
            book = extract_book(e["label"], e["content"])
            label_display = f" · 来源: {book}" if book != "(未识别)" else f" · {e['label']}"
            print(f"\n  [{i + 1}] {label_display}")
            for line in e["content"].split("\n"):
                stripped = line.strip()
                if stripped:
                    print(f"      {stripped}"[:130])
    else:
        print("  ⚠️  图数据库无返回。可能原因：")
        print("      1. 有残留进程锁着数据库（已自动清理，再试一次）")
        print("      2. 知识图谱为空（需先运行 quick_build.py 构建）")

    # ── ② 提示词 ──
    print(f"\n{'─' * 60}")
    print("② 发给大模型的提示词（重构版）")
    print(f"{'─' * 60}")

    if all_entries:
        print("""
  ┌─ System ──────────────────────────────┐
  │ 你是知识助手。根据上下文回答。          │
  │ 上下文不足时如实说不知道。               │
  └────────────────────────────────────────┘""")
        print(f"  ┌─ Context（{len(all_entries)} 个知识条目）─────────┐")
        for i, e in enumerate(all_entries[:8]):
            preview = e["content"][:100].replace("\n", " ").strip()
            book = extract_book(e["label"], e["content"])
            src = f"({book}) " if book != "(未识别)" else ""
            print(f"  │ [{i + 1}] {src}{e['label']}: {preview}...")
        if len(all_entries) > 8:
            print(f"  │ ... (共 {len(all_entries)} 条)")
        print("  └──────────────────────────────────────┘")

    print(f"""  ┌─ Question ───────────────────────────┐
  │ {question}
  └──────────────────────────────────────┘""")

    # ── ③ 回答 ──
    print(f"\n{'─' * 60}")
    print("③ 大模型回答")
    print(f"{'─' * 60}")
    print("  📗 基于以上上下文生成" if all_entries else "  ⚠️  上下文为空，来自 LLM 自身知识")

    results = await cognee.recall(query_text=question, datasets=[DS], top_k=3)
    for r in results:
        text = extract_content(r)
        # 对于最终回答，text 可能在 .text 字段直接就是答案文本
        t = getattr(r, "text", "") or ""
        if t and isinstance(t, str) and len(t) > 5:
            print(f"\n  {t}")
        elif text and "graph_completion" not in text:
            print(f"\n  {text}")

    print()


# ── 主入口 ──


async def main():
    print("━" * 60)
    print("  Cognee 知识库交互查询")
    print(f"  dataset: {DS} (5 篇文章)")
    print("━" * 60)

    # 自检
    _check_and_clear_lock()
    env_issues = _check_env()
    if env_issues:
        print("\n  💡 环境提示:")
        for issue in env_issues:
            print(f"     {issue}")
    print()

    print("  ①检索到的知识条目  ②发给LLM的提示词  ③LLM回答")
    print("  输入 quit 退出\n")

    while True:
        try:
            q = input("🔍 > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q.lower() == "quit":
            break
        await ask(q)

    print("👋 再见")


asyncio.run(main())
