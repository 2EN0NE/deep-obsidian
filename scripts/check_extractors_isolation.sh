#!/usr/bin/env bash
# Guards AGENTS.md 核心红线③: src/deep_obsidian/extractors/ must be pure
# functions with zero Cognee dependency (structural-layer extraction must
# never call an LLM or import Cognee). Nothing enforced this before —
# a single unnoticed `import cognee` in this directory would silently
# break the structural/semantic layer separation the architecture relies
# on. Run in CI's lint job.
set -euo pipefail

cd "$(dirname "$0")/.."

if rg -n '^\s*(import cognee|from cognee)' src/deep_obsidian/extractors/; then
  echo ""
  echo "ERROR: src/deep_obsidian/extractors/ must stay Cognee-free (AGENTS.md 核心红线③)." >&2
  echo "Structural extraction (wikilinks/frontmatter/tags) must be pure functions." >&2
  exit 1
fi

echo "OK: extractors/ has no Cognee dependency."
