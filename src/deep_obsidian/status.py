"""Status — show the ingest run state for a project (SPEC-003 / ADR-0009)."""

from __future__ import annotations

from pathlib import Path

from deep_obsidian.ingest._progress_state import is_process_alive, read_state
from deep_obsidian.settings import LEVEL_USER, resolve_config


async def status(
    dataset: str | None = None,
    *,
    vault_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict:
    """Report whether an ingest is currently running for this project.

    Returns a dict with a ``status`` key of one of:

    - ``idle``: no ingest is tracked.
    - ``running``: an ingest is in progress (its pid is alive); the dict
      also carries ``phase``/``current``/``total``/``current_file``/
      ``started_at``/``dataset``/``pid`` from the live progress state.
    - ``stale``: the last ingest was interrupted (its pid is dead)
      before it could clean up; the dict carries the same fields as
      ``running``, reflecting the last successfully persisted progress.
    """
    lookup = Path(vault_path) if vault_path else Path.cwd()
    # 配置层级解析（ADR-0014）：progress 状态文件在 config_dir 下。
    # config_path（--config）显式指定时直接使用。
    resolved = resolve_config(vault=lookup, cwd=Path.cwd(), config_path=config_path)

    state = read_state(
        resolved.config_dir,
        vault=resolved.vault if resolved.level == LEVEL_USER else None,
    )
    if state is None:
        return {"status": "idle", "dataset": dataset}

    pid = state.get("pid")
    if isinstance(pid, int) and is_process_alive(pid):
        return {"status": "running", **state}

    return {
        "status": "stale",
        "detail": "Ingest process exited without cleaning up — this is its last known progress.",
        **state,
    }
