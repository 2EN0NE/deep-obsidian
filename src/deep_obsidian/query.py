"""Query — LLM-synthesized answers from the knowledge graph."""

from __future__ import annotations

from pathlib import Path

# Lightweight import — cognee.exceptions does not trigger heavy init.
import cognee.exceptions
import litellm

from deep_obsidian.search import SearchLockContentionError
from deep_obsidian.search import search as do_search
from deep_obsidian.settings import resolve_config

# ── Transient LLM errors where a fallback answer is acceptable ──
# Cognee wraps litellm calls and may re-raise transient errors as its
# own CogneeTransientError, so we catch both.
_CogneeTransient: type[Exception] | None = getattr(cognee.exceptions, "CogneeTransientError", None)


def _read_llm_config(settings: dict) -> tuple[str, str | None, str | None, str | None]:
    """Extract LLM model, provider, endpoint, and api_key from settings.

    Reads the top-level ``llm`` section of settings.jsonc (ADR-0011) —
    the single source of truth.  Environment variables no longer
    override it (ADR-0012): the LLM config lives in the project file,
    not in the shell.

    Returns:
        (model, provider, endpoint, api_key) — provider, endpoint, and
        api_key may be None if not configured.
    """
    llm_cfg = settings.get("llm", {})
    model = llm_cfg.get("model") or "openai/gpt-5-mini"
    provider = llm_cfg.get("provider") or None
    endpoint = llm_cfg.get("endpoint") or None
    api_key = llm_cfg.get("api_key") or None
    return model, provider, endpoint, api_key


async def query(
    question: str,
    *,
    dataset: str | None = None,
    vault_path: str | Path | None = None,
    top_k: int = 5,
    config_path: str | Path | None = None,
) -> dict:
    """Answer a question using the knowledge graph, with source citations.

    Returns:
        dict with "answer" (str) and "sources" (list of source_file strings).
    """
    lookup = Path(vault_path) if vault_path else Path.cwd()
    # 配置层级解析（ADR-0014）：--config（显式）> 项目级（从 vault 或 cwd
    # 向上找 .deep-obsidian/）> 用户级 ~/.deep-obsidian（必需基础层）。
    # vault 定位数据。
    resolved = resolve_config(vault=lookup, cwd=Path.cwd(), config_path=config_path)
    dataset = dataset or resolved.settings["name"]

    # ADR-0012：触碰任何 Cognee API 前统一注入配置（query 经 do_search
    # 接触 Cognee，此处显式注入以保证约定完整、防御未来直接调用）。
    from deep_obsidian.config import inject_config

    inject_config(resolved)

    try:
        results = await do_search(
            question,
            dataset=dataset,
            vault_path=vault_path,
            top_k=top_k,
            config_path=config_path,
        )
    except SearchLockContentionError:
        return {
            "answer": (
                "The knowledge graph is currently being updated with new "
                "or changed notes. Please retry your question in a moment."
            ),
            "sources": [],
        }

    # Collect context and unique sources
    context_parts = []
    sources = []
    for r in results:
        src = r.get("source_file", "unknown")
        content = r.get("content", "")
        context_parts.append(f"[Source: {src}]\n{content}")
        if src and src not in sources:
            sources.append(src)

    if not context_parts:
        return {"answer": "No relevant information found.", "sources": []}

    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""You are a helpful assistant answering questions about a user's personal notes.

Use ONLY the provided context below to answer the question. If the context doesn't
contain enough information, say so honestly. Always cite which source(s) you used.

Context:
{context}

Question: {question}

Answer (include source references):"""

    llm_model, llm_provider, llm_endpoint, llm_api_key = _read_llm_config(resolved.settings)

    # Build transient-exception tuple (CogneeTransientError may be
    # missing in future Cognee versions — skip it gracefully).
    _transient: tuple[type[Exception], ...] = (
        litellm.exceptions.APIConnectionError,
        litellm.exceptions.Timeout,
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.RateLimitError,
    )
    if _CogneeTransient is not None:
        _transient += (_CogneeTransient,)

    # Build kwargs, omitting None values to let litellm use its defaults
    litellm_kwargs: dict = {
        "model": llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
    }
    if llm_endpoint:
        litellm_kwargs["api_base"] = llm_endpoint
    if llm_provider and llm_provider != "custom":
        litellm_kwargs["custom_llm_provider"] = llm_provider
    # When LLM_PROVIDER=custom, litellm infers the provider from the
    # model prefix (e.g. "openai/..." → OpenAI-compatible). Passing
    # custom_llm_provider="custom" breaks routing.
    if llm_api_key:
        litellm_kwargs["api_key"] = llm_api_key

    try:
        response = await litellm.acompletion(**litellm_kwargs)
        answer = response.choices[0].message.content
        if answer is None:
            answer = "_(LLM returned an empty response)_"
    except _transient:
        # Fallback when LLM is temporarily unavailable (network, overload, timeout).
        # Config/auth errors (wrong model, bad key) propagate — they need user action.
        snippets = [r.get("content", "")[:200] for r in results]
        answer = (
            "Based on your notes:\n\n"
            + "\n\n".join(f"- {s}" for s in snippets)
            + "\n\n_(LLM unavailable — showing raw retrieval results)_"
        )

    return {"answer": answer, "sources": sources}
