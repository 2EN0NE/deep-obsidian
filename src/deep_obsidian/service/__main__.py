"""Entry point for ``python -m deep_obsidian.service <project_root>``."""

import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python -m deep_obsidian.service <project_root>",
            file=sys.stderr,
        )
        sys.exit(1)

    import asyncio

    from deep_obsidian.service import run_service

    root = Path(sys.argv[1])
    asyncio.run(run_service(root))
