"""Config injection — settings.jsonc → Cognee (ADR-0012).

Reads LLM/Embedding settings from the project's settings.jsonc and
injects them into Cognee via ``cognee.config.set_*_config()`` (the
runtime setter API, not environment variables).  Non-Cognee runtime
variables (HuggingFace mirrors, connection-test toggles) go through
``os.environ`` because those libraries read the environment at import
time and have no equivalent setter.

Must be called before any Cognee API call (ingest/search/query/forget/
service all invoke it on entry).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from deep_obsidian.settings import ResolvedConfig

if TYPE_CHECKING:
    pass

# settings.jsonc key path → Cognee setter target key.
_LLM_KEY_MAP = {
    "provider": "llm_provider",
    "model": "llm_model",
    "api_key": "llm_api_key",
    "endpoint": "llm_endpoint",
}
_EMBEDDING_KEY_MAP = {
    "provider": "embedding_provider",
    "model": "embedding_model",
    "dimensions": "embedding_dimensions",
    "endpoint": "embedding_endpoint",
    "api_key": "embedding_api_key",
}

# network.* keys → environment variable names (lowercased key → env name).
_NETWORK_ENV_MAP = {
    "hf_endpoint": "HF_ENDPOINT",
    "hf_hub_offline": "HF_HUB_OFFLINE",
    "cognee_skip_connection_test": "COGNEE_SKIP_CONNECTION_TEST",
}


def _map_section(section: dict | None, key_map: dict[str, str]) -> dict[str, Any]:
    """Map a settings.jsonc section dict to Cognee setter kwargs.

    Only keys present in the section AND in ``key_map`` are included,
    so absent/optional values are simply not set (Cognee keeps its
    defaults).  Empty-string values are skipped (they mean "unset").
    """
    if not section:
        return {}
    out: dict[str, Any] = {}
    for src_key, dst_key in key_map.items():
        value = section.get(src_key)
        if value is None or value == "":
            continue
        out[dst_key] = value
    return out


def _inject_network(network: dict | None) -> None:
    """Inject network.* settings into os.environ (for runtime libraries)."""
    if not network:
        return
    for src_key, env_name in _NETWORK_ENV_MAP.items():
        value = network.get(src_key)
        if value is None or value == "":
            # 未设置：不干预环境（shell 已 export 的值保留生效）。
            continue
        if isinstance(value, bool):
            if not value:
                # 显式 false = 明确关闭：必须清除环境中已有的同名变量。
                # 只"不注入"是不够的 —— 残留的旧值（shell export 或先前
                # 注入的 true）会继续生效，覆盖 settings 的显式关闭意图
                # （settings 是唯一配置源）。
                os.environ.pop(env_name, None)
                continue
            os.environ[env_name] = "true"
        else:
            os.environ[env_name] = str(value)


def inject_config(resolved: ResolvedConfig) -> None:
    """Inject merged LLM/Embedding/network config into Cognee (ADR-0012/0014).

    Reads the *merged* settings from a :class:`ResolvedConfig` (the
    three-level hierarchy already resolved by ``resolve_config``) and
    pushes LLM/Embedding into ``cognee.config.set_*_config()`` plus
    network.* into ``os.environ``.

    Idempotent — safe to call multiple times (Cognee setters overwrite).
    """
    import cognee

    settings = resolved.settings

    llm_kwargs = _map_section(settings.get("llm"), _LLM_KEY_MAP)
    if llm_kwargs:
        # cognee 无 py.typed，pyright 报 attr-defined 属既有类型债务
        # （ingest/forget/search 同样用法）；此处显式忽略。
        cognee.config.set_llm_config(llm_kwargs)  # type: ignore[attr-defined]

    embedding_kwargs = _map_section(settings.get("embedding"), _EMBEDDING_KEY_MAP)
    if embedding_kwargs:
        cognee.config.set_embedding_config(embedding_kwargs)  # type: ignore[attr-defined]

    _inject_network(settings.get("network"))
