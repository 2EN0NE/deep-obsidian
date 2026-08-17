"""deep-obsidian — Obsidian vault to Cognee knowledge graph.

Submodules are loaded lazily so that Cognee is not imported until
actually needed.  This keeps ``--help`` and other fast-path CLI
commands free of Cognee's import-time logging.
"""

__all__ = ["config", "forget", "ingest", "query", "search", "service", "status"]
__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "config":
        import deep_obsidian.config  # noqa: F401

        return deep_obsidian.config
    if name == "forget":
        from deep_obsidian.forget import forget

        return forget
    if name == "ingest":
        from deep_obsidian.ingest import ingest

        return ingest
    if name == "query":
        from deep_obsidian.query import query

        return query
    if name == "search":
        from deep_obsidian.search import search

        return search
    if name == "service":
        import deep_obsidian.service  # noqa: F811

        return deep_obsidian.service
    if name == "status":
        from deep_obsidian.status import status

        return status
    raise AttributeError(f"module 'deep_obsidian' has no attribute {name!r}")
