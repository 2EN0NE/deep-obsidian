"""deep-obsidian — Obsidian vault to Cognee knowledge graph.

Submodules (ingest, search, forget, status) are loaded lazily so that
Cognee is not imported until it is actually needed.  This keeps ``--help``
and other fast-path CLI commands free of Cognee's import-time logging.
"""

__all__ = ["ingest", "search", "status", "forget"]
__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "forget":
        from deep_obsidian.forget import forget

        return forget
    if name == "ingest":
        from deep_obsidian.ingest import ingest

        return ingest
    if name == "search":
        from deep_obsidian.search import search

        return search
    if name == "status":
        from deep_obsidian.status import status

        return status
    raise AttributeError(f"module 'deep_obsidian' has no attribute {name!r}")
