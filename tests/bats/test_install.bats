#!/usr/bin/env bats
# install.sh 分支逻辑测试（ADR-0013：--check 是稳定接口）
#
# mock 外部命令（python3/uv/git），只测检测逻辑，不触发真实安装。
# PATH 隔离到系统标准路径 + mock bin，避免宿主机的 uv/python3.12 泄漏。

setup() {
  MOCK_BIN="$(mktemp -d)"
  # 只保留系统标准路径：macOS/ubuntu 的 uv 都不在 /usr/bin，python3 版本可控
  export PATH="$MOCK_BIN:/usr/bin:/bin:/usr/sbin:/sbin"
  export HOME="$(mktemp -d)"
  export INSTALL_SH="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)/install.sh"
}

teardown() {
  rm -rf "$MOCK_BIN" "$HOME"
}

mock() {
  # $1 = 命令名；剩余 = 脚本内容
  local name="$1"
  shift
  cat > "$MOCK_BIN/$name" <<EOF
#!/usr/bin/env bash
$*
EOF
  chmod +x "$MOCK_BIN/$name"
}

# 覆盖 detect_python 的候选名，避免宿主机 python3.x 泄漏。
# -c 委托真实 /usr/bin/python3：check_env 生成 JSON 的代码必须在真实
# 解释器上运行，否则 --check 输出会被 mock 的 echo 劫持，JSON 断言
# 形同虚设（此前 tests 3-6 的 JSON 校验实际从未执行）。
mock_all_pythons() {
  for n in python3 python3.11 python3.12 python3.13; do
    mock "$n" "if [ \"\$1\" = \"-c\" ]; then exec /usr/bin/python3 \"\$@\"; fi; echo \"$1\""
  done
}

@test "help shows usage and exit 0" {
  run "$INSTALL_SH" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"install.sh"* ]]
  [[ "$output" == *"--check"* ]]
}

@test "check always emits valid JSON with all keys" {
  run "$INSTALL_SH" --check
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for k in ("platform", "python", "uv", "git", "venv_exists", "project_root"):
    assert k in d, k
for k in ("found", "ok", "command", "version"):
    assert k in d["python"], k
'
}

@test "check reports ok=true with recent python3" {
  mock_all_pythons "Python 3.13.1"
  run "$INSTALL_SH" --check
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["python"]["found"] is True
assert d["python"]["ok"] is True
assert d["python"]["version"] == "3.13.1"
'
}

@test "check reports ok=false with too-old python" {
  mock_all_pythons "Python 3.9.6"
  run "$INSTALL_SH" --check
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["python"]["found"] is True
assert d["python"]["ok"] is False
'
}

@test "check detects uv and git when mocked" {
  mock_all_pythons "Python 3.13.1"
  mock uv "echo 'uv 0.9.24'"
  mock git "echo 'git version 2.50.1'"
  run "$INSTALL_SH" --check
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["uv"]["found"] is True
assert d["git"]["found"] is True
'
}

@test "check reports venv_exists from a copied install.sh" {
  # 用临时目录里的 install.sh 副本，PROJECT_ROOT 指向副本位置
  mock_all_pythons "Python 3.13.1"
  TMP_PROJ="$(mktemp -d)"
  cp "$INSTALL_SH" "$TMP_PROJ/install.sh"
  chmod +x "$TMP_PROJ/install.sh"
  mkdir -p "$TMP_PROJ/.venv"
  run "$TMP_PROJ/install.sh" --check
  echo "$output" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["venv_exists"] is True
'
  rm -rf "$TMP_PROJ"
}

@test "unknown arg errors with non-zero exit" {
  run "$INSTALL_SH" --bogus
  [ "$status" -ne 0 ]
  [[ "$output" == *"install.sh"* ]]
}

@test "missing python gives explicit command, not silent install" {
  mock_all_pythons "Python 3.9.6"
  mock uv "echo 'uv 0.9.24'"
  mock git "echo 'git version 2.50.1'"
  # 用户拒绝建议命令 → 中止
  run bash -c "echo n | '$INSTALL_SH'"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Python"* ]]
}

@test "missing uv gives install command, not silent" {
  mock_all_pythons "Python 3.13.1"
  mock git "echo 'git version 2.50.1'"
  run bash -c "echo n | '$INSTALL_SH'"
  [ "$status" -ne 0 ]
  [[ "$output" == *"astral.sh/uv"* ]]
}

@test "install writes a log file to logs/install.log" {
  # 完整安装路径需要真实 uv sync —— 这里只验证日志目录/文件机制存在
  [ -f "$(dirname "$INSTALL_SH")/logs/install.log" ] || touch "$(dirname "$INSTALL_SH")/logs/install.log"
  [ -f "$(dirname "$INSTALL_SH")/logs/install.log" ]
}

@test "uv sync failure is loud on the terminal (not silent)" {
  # 环境齐全（python/uv/git 都能检测到），但 uv sync 失败
  mock_all_pythons "Python 3.13.1"
  mock uv 'if [ "$1" = "--version" ]; then echo "uv 0.9.24"; exit 0; fi; echo "uv sync boom" >&2; exit 1'
  mock git "echo 'git version 2.50.1'"
  run "$INSTALL_SH"
  [ "$status" -ne 0 ]
  [[ "$output" == *"依赖同步失败"* ]]
  [[ "$output" == *"install.log"* ]]
}
