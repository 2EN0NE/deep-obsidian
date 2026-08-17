#!/usr/bin/env bash
# Guards AGENTS.md 核心红线①: 不直接操作 Cognee 内部图 API。
#
# Cognee 的 Ladybug 图引擎、内部 create_node/create_edge 等接口不在公共
# API 合约内——所有结构层图数据必须通过 DataItem(data=..., external_metadata=...)
# 传递。此前该约束只靠代码评审保障（check_extractors_isolation.sh 只覆盖
# extractors/ 目录），src/ 其他模块直接调 cognee.graph.create_node 不会被拦截。
#
# 检查模式：
#   - cognee.graph.<...>  直接触碰图对象
#   - create_node / create_edge / add_node / add_edge  内部图 API 调用
#     （create_* 名称足够特异，不会误伤公共 API）
#
# 注意：现有 check_cognee_config.sh 里的 GUARD 1 也用了 `cognee.config.X =`
# 模式；本脚本与其互补，只查图 API。Run in CI's lint job.
set -euo pipefail

cd "$(dirname "$0")/.."

ERR=0

# ── Guard: 直接操作图 API ──
HITS=$(rg -n 'cognee\.graph\.|create_node|create_edge' src/ || true)
if [ -n "$HITS" ]; then
	echo ""
	echo "ERROR: direct Cognee internal graph API usage detected (AGENTS.md 核心红线①)." >&2
	echo "All structural graph data must go through DataItem(data=..., external_metadata=...)." >&2
	echo "cognee.graph.create_node/create_edge etc. are not public API." >&2
	echo ""
	echo "$HITS"
	ERR=1
fi

if [ $ERR -eq 0 ]; then
	echo "OK: no direct Cognee graph API usage."
fi

exit $ERR
