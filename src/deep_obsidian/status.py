"""Status — show ingest progress for a dataset."""


async def status(dataset: str | None = None) -> dict:
    """Show ingest progress and graph statistics.

    Not yet implemented — returns a placeholder indicating work-in-progress.
    """
    return {
        "dataset": dataset or "default",
        "status": "not_implemented",
        "message": "Status tracking is not yet available.",
    }
