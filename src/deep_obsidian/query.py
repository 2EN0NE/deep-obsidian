"""Query — LLM-synthesized answers from the knowledge graph."""

from __future__ import annotations

from pathlib import Path

# Lightweight import — cognee.exceptions does not trigger heavy init.
import cognee.exceptions
import litellm

from deep_obsidian.search import search as do_search
from deep_obsidian.settings import find_project_root, read_settings

# ── Transient LLM errors where a fallback answer is acceptable ──
# Cognee wraps litellm calls and may re-raise transient errors as its
# own CogneeTransientError, so we catch both.
_CogneeTransient: type[Exception] | None = getattr(cognee.exceptions, "CogneeTransientError", None)


def _read_llm_config(settings: dict) -> tuple[str, str | None, str | None, str | None]:
    """Extract LLM model, provider, endpoint, and api_key from settings.

    Environment variables (LLM_MODEL, LLM_PROVIDER, LLM_ENDPOINT,
    LLM_API_KEY) take precedence over settings.json values, matching
    Cognee's own resolution order.

    Returns:
        (model, provider, endpoint, api_key) — provider, endpoint, and
        api_key may be None if not configured.
    """
    import os as _os

    backend = settings.get("backend", {})
    if backend.get("type") != "cognee":
        raise RuntimeError(
            f"Unsupported backend type: {backend.get('type', 'unknown')!r}. "
            f"Only 'cognee' is currently supported."
        )
    cognee_cfg = backend.get("cognee", {})

    # Env vars take precedence (same order Cognee uses via dotenv/pydantic-settings)
    model = _os.environ.get("LLM_MODEL") or cognee_cfg.get("llm_model", "deepseek-chat")
    provider = _os.environ.get("LLM_PROVIDER") or cognee_cfg.get("llm_provider") or None
    endpoint = _os.environ.get("LLM_ENDPOINT") or cognee_cfg.get("llm_endpoint") or None
    api_key = _os.environ.get("LLM_API_KEY") or cognee_cfg.get("llm_api_key") or None
    return model, provider, endpoint, api_key


async def query(
    question: str,
    *,
    dataset: str | None = None,
    vault_path: str | Path | None = None,
    top_k: int = 5,
) -> dict:
    """Answer a question using the knowledge graph, with source citations.

    Returns:
        dict with "answer" (str) and "sources" (list of source_file strings).
    """
    lookup = Path(vault_path) if vault_path else Path.cwd()
    project_root = find_project_root(lookup)
    if project_root is None:
        raise RuntimeError(
            "No .deep-obsidian/ directory found. "
            "Run 'deep-obsidian init' first in the project root."
        )
    _settings = read_settings(project_root)
    dataset = dataset or _settings["name"]

    results = await do_search(question, dataset=dataset, vault_path=vault_path, top_k=top_k)

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

    llm_model, llm_provider, llm_endpoint, llm_api_key = _read_llm_config(_settings)

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
