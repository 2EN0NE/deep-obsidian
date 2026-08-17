"""E2E tests for install.sh — full flow with external downloads mocked.

The CI e2e job runs tests/e2e/ on ubuntu.  install.sh's full path would
download uv/python from the network, which is slow and non-hermetic, so
these tests mock the external pieces (uv, brew/xcode) and exercise the
script's own branching: environment detection, log writing, venv
handling, and the --check contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = ROOT / "install.sh"

pytestmark = pytest.mark.e2e


def _run_install(
    *args: str, env: dict | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess:
    """Run install.sh with an isolated PATH and HOME."""
    full_env = dict(os.environ)
    full_env.update(env or {})
    return subprocess.run(
        [str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        input=stdin,
        env=full_env,
        cwd=ROOT,
        timeout=120,
    )


@pytest.fixture
def mock_env(tmp_path):
    """PATH 隔离 + 可放置 mock 命令的 bin 目录。"""
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return {
        "_MOCK_BIN": str(mock_bin),
        "HOME": str(home),
        "PATH": f"{mock_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
    }


def _make_mock(mock_bin: Path, name: str, body: str) -> None:
    p = mock_bin / name
    p.write_text(f"#!/usr/bin/env bash\n{body}\n")
    p.chmod(0o755)


def _mock_python(mock_bin: Path, version: str) -> None:
    """Mock python3*: --version 输出版本号，-c 时委托真实 python3。

    install.sh 的 check_env 会用 python3 -c 生成 JSON，所以 mock 必须
    放行 -c 调用，否则 JSON 生成会被 mock 的 echo 劫持。
    """
    real_python = Path(sys.executable)
    body = f"""
if [ "$1" = "-c" ]; then
  exec "{real_python}" "$@"
fi
echo 'Python {version}'
"""
    for name in ("python3", "python3.11", "python3.12", "python3.13"):
        _make_mock(mock_bin, name, body)


class TestCheckMode:
    """install.sh --check 是稳定接口（ADR-0013）"""

    def test_emits_valid_json(self, mock_env):
        r = _run_install("--check", env=mock_env)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["platform"] in ("macos", "linux", "windows")
        assert "python" in data and "uv" in data and "git" in data
        assert "venv_exists" in data

    def test_reports_python_ok_with_mock(self, mock_env, tmp_path):
        _mock_python(Path(mock_env["_MOCK_BIN"]), "3.13.1")
        r = _run_install("--check", env=mock_env)
        data = json.loads(r.stdout)
        assert data["python"]["ok"] is True
        assert data["python"]["version"] == "3.13.1"

    def test_reports_python_stale_with_mock(self, mock_env, tmp_path):
        _mock_python(Path(mock_env["_MOCK_BIN"]), "3.9.6")
        r = _run_install("--check", env=mock_env)
        data = json.loads(r.stdout)
        assert data["python"]["found"] is True
        assert data["python"]["ok"] is False


class TestFullFlow:
    """完整流程（mock 外部下载）"""

    def test_missing_python_aborts_with_guidance(self, mock_env, tmp_path):
        """缺 Python 时不静默安装，给出命令并等用户确认。"""
        mock_bin = Path(mock_env["_MOCK_BIN"])
        _mock_python(mock_bin, "3.9.6")
        _make_mock(mock_bin, "uv", "echo 'uv 0.9.24'")
        _make_mock(mock_bin, "git", "echo 'git version 2.50.1'")

        r = _run_install(env=mock_env, stdin="n\n")
        assert r.returncode != 0
        assert "Python" in r.stdout
        assert "install.sh" in r.stdout  # 提示重跑

    def test_missing_uv_aborts_with_guidance(self, mock_env, tmp_path):
        mock_bin = Path(mock_env["_MOCK_BIN"])
        _mock_python(mock_bin, "3.13.1")
        _make_mock(mock_bin, "git", "echo 'git version 2.50.1'")

        r = _run_install(env=mock_env, stdin="n\n")
        assert r.returncode != 0
        assert "uv" in r.stdout

    def test_install_writes_log_file(self, mock_env, tmp_path):
        """--check 不写日志（无安装动作）；完整流程会写 logs/install.log。"""
        log_path = ROOT / "logs" / "install.log"
        # 触发一次完整流程（缺 uv 中止），应产生日志
        _mock_python(Path(mock_env["_MOCK_BIN"]), "3.13.1")
        r = _run_install(env=mock_env, stdin="n\n")
        assert r.returncode != 0
        assert log_path.is_file()
        content = log_path.read_text(encoding="utf-8")
        assert "deep-obsidian install" in content
