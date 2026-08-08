#!/usr/bin/env bash
# Guards AGENTS.md 核心红线④: cognee.config.data_root_directory and
# cognee.config.system_root_directory MUST be called as functions
# (e.g. `cognee.config.data_root_directory(str(path))`), NOT assigned
# as attributes (`cognee.config.data_root_directory = str(path)`).
#
# Python allows attribute assignment on class properties — it is
# syntactically legal, passes pyright, and throws no runtime error —
# but it silently replaces the @staticmethod with a plain string,
# meaning the actual Cognee setter logic (which reads from
# get_base_config()) never runs. This bug existed in ingest/forget/
# search for weeks before ADR-0007 caught it.
#
# This script also checks that BOTH config values are set together
# in every integration point, preventing the companion bug where only
# data_root_directory was set without system_root_directory (ADR-0006).
#
# Run in CI's lint job.
set -euo pipefail

cd "$(dirname "$0")/.."

ERR=0

echo "=== AGENTS.md 规则守卫 ==="

# ── Guard 1: 属性赋值而非函数调用 ──
# Search for `cognee.config.X =` (attribute assignment, which is a no-op)
ATTR_ASSIGN=$(rg -n 'cognee\.config\.\w+\s*=' src/ || true)
if [ -n "$ATTR_ASSIGN" ]; then
	echo ""
	echo "ERROR: cognee.config setter used as attribute assignment (silent no-op)." >&2
	echo "Must call as a function: cognee.config.X(str(path)), not cognee.config.X = str(path)." >&2
	echo "See ADR-0007 and AGENTS.md 核心红线④." >&2
	echo ""
	echo "$ATTR_ASSIGN"
	ERR=1
fi

# ── Guard 2: 每个 Cognee 集成点必须同时设置两个 config ──
# Find files that reference cognee.config, then check each one has BOTH
# data_root_directory AND system_root_directory called.
COGNE_CONFIG_FILES=$(rg -l 'cognee\.config\.' src/ || true)
if [ -n "$COGNE_CONFIG_FILES" ]; then
	for f in $COGNE_CONFIG_FILES; do
		HAS_DATA=$(rg -c 'cognee\.config\.data_root_directory\(' "$f" || true)
		HAS_SYSTEM=$(rg -c 'cognee\.config\.system_root_directory\(' "$f" || true)
		if [ "${HAS_DATA:-0}" -gt 0 ] && [ "${HAS_SYSTEM:-0}" -eq 0 ]; then
			echo ""
			echo "ERROR: $f sets data_root_directory but NOT system_root_directory." >&2
			echo "Both must be set together for per-vault data isolation (ADR-0006, AGENTS.md 核心红线④)." >&2
			ERR=1
		fi
		if [ "${HAS_SYSTEM:-0}" -gt 0 ] && [ "${HAS_DATA:-0}" -eq 0 ]; then
			echo ""
			echo "ERROR: $f sets system_root_directory but NOT data_root_directory." >&2
			echo "Both must be set together (ADR-0006)." >&2
			ERR=1
		fi
	done
fi

if [ $ERR -eq 0 ]; then
	echo "OK: cognee.config usage follows AGENTS.md 核心红线④."
fi

exit $ERR
