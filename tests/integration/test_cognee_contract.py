"""Mock↔真实 cognee API 契约一致性测试。

背景（ADR-0006 教训）：compat job（.github/workflows/ci.yml schedule）用
真实 cognee 跑 tests/，但所有测试都走 mock_llm——mock 的手工签名不随真实
API 变化而失效。若 cognee 升级改变 add/recall/update/forget 的签名，mock
测不出项目代码传参错误，只有真实运行时才炸。

本文件用两条防线覆盖：
  1. AST 扫描 src/deep_obsidian/ 里所有 ``cognee.<api>(...)`` 调用点，
     断言其关键字参数名 ⊆ 已安装 cognee 的真实签名参数集。
     （对 add/cognify 放行——真实签名带 **kwargs，任何 kwarg 都合法。）
  2. conftest 的 mock 白名单（UPDATE_ALLOWED_KWARGS / RECALL_ALLOWED_KWARGS）
     ⊆ 真实签名参数集，防止 mock 比真实更宽松。

两个测试都在 integration 层（允许 import cognee）；compat job 每周用最新
cognee 跑全量，正是本测试捕获漂移的时机。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from tests.conftest import RECALL_ALLOWED_KWARGS, UPDATE_ALLOWED_KWARGS

pytestmark = pytest.mark.integration

_SRC = Path(__file__).resolve().parents[2] / "src" / "deep_obsidian"
_API_FNS = {"add", "update", "forget", "recall", "cognify"}


def _kwarg_names(fn) -> set[str]:
    """所有可用关键字参数名（位置/关键字 与 纯关键字）。"""
    sig = inspect.signature(fn)
    return {
        name
        for name, p in sig.parameters.items()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }


def _has_var_kwargs(fn) -> bool:
    return any(p.kind == p.VAR_KEYWORD for p in inspect.signature(fn).parameters.values())


def _collect_project_calls() -> list[tuple[str, int, str, list[str]]]:
    """AST 扫描 src/ 里 cognee.<api>(...) 调用点。

    Returns: [(file, lineno, fn_name, kwarg_names)].
    """
    calls: list[tuple[str, int, str, list[str]]] = []
    for py in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "cognee" or func.attr not in _API_FNS:
                continue
            kwargs = [kw.arg for kw in node.keywords if kw.arg]
            calls.append((str(py.relative_to(_SRC)), node.lineno, func.attr, kwargs))
    return calls


class TestProjectCallsMatchRealSignature:
    """项目代码传参必须命中真实 cognee 签名的关键字参数。"""

    def test_every_call_site_uses_real_kwargs(self):
        import cognee

        calls = _collect_project_calls()
        assert calls, "AST 扫描应至少发现一个 cognee API 调用点"
        for file, lineno, fn_name, kwargs in calls:
            real_fn = getattr(cognee, fn_name)
            if _has_var_kwargs(real_fn):
                continue  # add/cognify 真实接受任意 kwarg（**kwargs）
            real_kw = _kwarg_names(real_fn)
            bad = set(kwargs) - real_kw
            assert not bad, (
                f"{file}:{lineno} cognee.{fn_name}() 传了真实签名没有的参数: "
                f"{sorted(bad)}（真实签名无 **kwargs，此调用在真实环境必炸）"
            )

    def test_mock_whitelists_subset_of_real_signature(self):
        """conftest 的 mock 白名单不得比真实签名更宽松。"""
        import cognee

        real_recall = _kwarg_names(cognee.recall)  # type: ignore[attr-defined]
        real_update = _kwarg_names(cognee.update)  # type: ignore[attr-defined]
        extra_recall = RECALL_ALLOWED_KWARGS - real_recall
        extra_update = UPDATE_ALLOWED_KWARGS - real_update
        assert not extra_recall, f"mock recall 白名单含真实签名没有的参数: {sorted(extra_recall)}"
        assert not extra_update, f"mock update 白名单含真实签名没有的参数: {sorted(extra_update)}"
