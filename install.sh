#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# deep-obsidian installer — environment check + dependency install
#
# 职责（ADR-0013）:
#   - 检测环境（Python 3.11+ / uv / git）
#   - 缺依赖时给出明确命令，让用户确认后执行（不静默安装）
#   - uv sync（不带 --dev，不装开发依赖）
#   - 验证 deep-obsidian CLI 可用
#   - 幂等：.venv/ 已存在则修复式刷新；--reset 删 .venv/ 重建
#
# 配置引导不在这里 —— 那是 `deep-obsidian init` 的职责。
#
# 可观测性:
#   - 全程日志写 logs/install.log（带时间戳）
#   - 终端显示精简进度 [1/5] ...
#   - --check 只跑环境检测，输出 JSON（供测试与排障）
#
# 用法:
#   ./install.sh            # 完整安装（幂等）
#   ./install.sh --check    # 只检测环境，输出 JSON
#   ./install.sh --reset    # 删除 .venv/ 后重新安装
#   ./install.sh --help     # 帮助
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/install.log"
VENV_DIR="$PROJECT_ROOT/.venv"

# 平台检测 —— macOS first，Linux 预留（ADR-0013）
OS_NAME="$(uname -s)"
case "$OS_NAME" in
Darwin) PLATFORM="macos" ;;
Linux) PLATFORM="linux" ;;
MINGW* | MSYS* | CYGWIN*) PLATFORM="windows" ;;
*) PLATFORM="unknown" ;;
esac

MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

# ── 日志 ─────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
exec 3>&1 # 保存原始 stdout
# 终端精简进度 + 详细日志落盘
log() {
	local msg
	msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
	echo "$msg" >>"$LOG_FILE"
	echo "$*" >&3
}
warn() {
	local msg
	msg="[$(date '+%Y-%m-%d %H:%M:%S')] [warn] $*"
	echo "$msg" >>"$LOG_FILE"
	echo "⚠️  $*" >&3
}
die() {
	echo "[$(date '+%Y-%m-%d %H:%M:%S')] [error] $*" >>"$LOG_FILE"
	echo "❌ $*" >&3
	exit 1
}

# ── 检测函数 ─────────────────────────────────────────────────────────
version_at_least() {
	# $1 = actual version string (e.g. "3.13.1"); $2,$3 = required major.minor
	local major minor
	IFS='.' read -r major minor _ <<<"$1"
	[ "${major:-0}" -gt "$2" ] || { [ "${major:-0}" -eq "$2" ] && [ "${minor:-0}" -ge "$3" ]; }
}

detect_python() {
	# 返回可用的 python3 命令路径（>=3.11），找不到返回 1
	local c ver
	for c in python3 python3.13 python3.12 python3.11; do
		if command -v "$c" >/dev/null 2>&1; then
			ver="$("$c" --version 2>/dev/null | sed 's/Python //')"
			if version_at_least "$ver" "$MIN_PYTHON_MAJOR" "$MIN_PYTHON_MINOR"; then
				echo "$c|$ver"
				return 0
			fi
		fi
	done
	return 1
}

detect_uv() {
	command -v uv >/dev/null 2>&1 && {
		echo "uv|$(uv --version 2>/dev/null | sed 's/uv //')"
		return 0
	}
	return 1
}

detect_git() {
	command -v git >/dev/null 2>&1 && {
		echo "git|$(git --version 2>/dev/null | sed 's/git version //')"
		return 0
	}
	return 1
}

# ── --check 模式：只输出环境 JSON ────────────────────────────────────
check_env() {
	local py="" uv_="" git_=""
	py="$(detect_python || true)"
	uv_="$(detect_uv || true)"
	git_="$(detect_git || true)"

	local py_ver="" py_cmd="" uv_ver="" git_ver=""
	[ -n "$py" ] && {
		py_cmd="${py%%|*}"
		py_ver="${py##*|}"
	}
	[ -n "$uv_" ] && uv_ver="${uv_##*|}"
	[ -n "$git_" ] && git_ver="${git_##*|}"

	local venv="false"
	[ -d "$VENV_DIR" ] && venv="true"

	# python 可用性：任一候选命令（python3 / python3.13/12/11）存在即
	# found=true；只有 detect_python 命中（版本 >= 3.11）才 ok=true。
	# 不能只看 `python3` 这一个名字 —— 只装了 python3.13 的机器上
	# found/ok 会自相矛盾。
	local py_found="false" py_ok="false"
	for c in python3 python3.13 python3.12 python3.11; do
		if command -v "$c" >/dev/null 2>&1; then
			py_found="true"
			break
		fi
	done
	[ -n "$py" ] && py_ok="true"

	local uv_found="false" git_found="false"
	[ -n "$uv_ver" ] && uv_found="true"
	[ -n "$git_ver" ] && git_found="true"

	# 生成 JSON：优先用检测到的 python（版本正确）。完全没有可用 python
	# 时用 bash 直接拼装 —— --check 是排障接口，缺 python 恰是最需要它
	# 工作的场景，不能让 python3 -c 的失败把 JSON 吞掉（回归）。
	if [ -n "$py_cmd" ]; then
		"$py_cmd" -c '
import json, sys
print(json.dumps({
  "platform": sys.argv[1],
  "python": {
    "found": sys.argv[2] == "true",
    "ok": sys.argv[3] == "true",
    "command": sys.argv[4],
    "version": sys.argv[5],
  },
  "uv": {"found": sys.argv[6] != "", "version": sys.argv[6]},
  "git": {"found": sys.argv[7] != "", "version": sys.argv[7]},
  "venv_exists": sys.argv[8] == "true",
  "project_root": sys.argv[9],
}, ensure_ascii=False, indent=2))
' "$PLATFORM" "$py_found" "$py_ok" "$py_cmd" "$py_ver" "$uv_ver" "$git_ver" "$venv" "$PROJECT_ROOT"
	else
		cat <<EOF
{
  "platform": "$PLATFORM",
  "python": {
    "found": $py_found,
    "ok": $py_ok,
    "command": "$py_cmd",
    "version": "$py_ver"
  },
  "uv": {"found": $uv_found, "version": "$uv_ver"},
  "git": {"found": $git_found, "version": "$git_ver"},
  "venv_exists": $venv,
  "project_root": "$PROJECT_ROOT"
}
EOF
	fi
}

# ── 缺依赖引导 ───────────────────────────────────────────────────────
confirm_or_die() {
	# $1 = 描述, $2 = 建议命令
	warn "缺少 $1。"
	echo "  建议执行以下命令安装（需要你确认，不会自动执行）:"
	echo "    $2"
	echo "  也可以手动安装后重新运行 ./install.sh"
	echo -n "  是否现在执行该命令？[y/N] " >&3
	read -r ans
	# macOS 自带 bash 3.2 不支持 ${var,,} —— 用 tr 做大小写转换（POSIX 兼容）
	if [ "$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')" = "y" ] ||
		[ "$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')" = "yes" ]; then
		log "执行: $2"
		eval "$2" || die "命令执行失败: $2"
	else
		die "缺少 $1，安装中止。安装后重新运行 ./install.sh 即可。"
	fi
}

install_uv_cmd() {
	if [ "$PLATFORM" = "macos" ] || [ "$PLATFORM" = "linux" ]; then
		echo 'curl -LsSf https://astral.sh/uv/install.sh | sh'
	else
		echo 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"'
	fi
}

# ── 主流程 ───────────────────────────────────────────────────────────
usage() {
	cat <<'EOF'
deep-obsidian installer

用法:
  ./install.sh            完整安装（幂等，可重复执行）
  ./install.sh --check    只检测环境，输出 JSON
  ./install.sh --reset    删除 .venv/ 后重新安装
  ./install.sh --help     显示本帮助

日志: logs/install.log
EOF
}

main() {
	local reset="false"
	for arg in "$@"; do
		case "$arg" in
		--check)
			check_env
			exit 0
			;;
		--reset) reset="true" ;;
		--help | -h)
			usage
			exit 0
			;;
		*) die "未知参数: $arg（运行 ./install.sh --help 查看用法）" ;;
		esac
	done

	log "=== deep-obsidian install 开始 (platform=$PLATFORM) ==="

	# [1/5] 平台检查
	if [ "$PLATFORM" = "unknown" ]; then
		die "无法识别的平台 ($OS_NAME)。目前支持 macOS / Linux / Windows(WSL)。"
	fi
	log "[1/5] 平台: $PLATFORM"

	# [2/5] Python
	local py_info=""
	if ! py_info="$(detect_python)"; then
		if [ "$PLATFORM" = "macos" ]; then
			confirm_or_die "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+" \
				"brew install python@3.12"
		else
			confirm_or_die "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+" \
				"请安装 Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+（参考 https://www.python.org/downloads/）"
		fi
		py_info="$(detect_python)" || die "Python 安装后仍不可用。"
	fi
	log "[2/5] Python: ${py_info##*|} ($(command -v "${py_info%%|*}"))"

	# [3/5] uv
	local uv_info=""
	if ! uv_info="$(detect_uv)"; then
		confirm_or_die "uv（Python 包管理器）" "$(install_uv_cmd)"
		uv_info="$(detect_uv)" || die "uv 安装后仍不可用。"
	fi
	log "[3/5] uv: ${uv_info##*|}"

	# [4/5] git
	if ! detect_git >/dev/null; then
		if [ "$PLATFORM" = "macos" ]; then
			confirm_or_die "git" "xcode-select --install"
		else
			confirm_or_die "git" "请安装 git（参考 https://git-scm.com/downloads）"
		fi
	fi
	log "[4/5] git: 可用"

	# [5/5] 虚拟环境 + 依赖
	if [ "$reset" = "true" ] && [ -d "$VENV_DIR" ]; then
		log "  --reset: 删除 $VENV_DIR"
		rm -rf "$VENV_DIR"
	fi
	if [ -d "$VENV_DIR" ]; then
		log "  .venv/ 已存在，走修复式刷新（uv sync 幂等）"
	else
		log "  首次安装，创建虚拟环境"
	fi
	if ! uv sync --no-dev --project "$PROJECT_ROOT" >>"$LOG_FILE" 2>&1; then
		tail -30 "$LOG_FILE" >&3
		die "依赖同步失败（uv sync）。完整日志: $LOG_FILE"
	fi
	log "  依赖同步完成"

	# 验证
	if [ -x "$VENV_DIR/bin/deep-obsidian" ]; then
		log "  验证 CLI 可用"
		"$VENV_DIR/bin/deep-obsidian" --version >/dev/null 2>&1 ||
			die "deep-obsidian CLI 验证失败。请查看 $LOG_FILE"
	fi

	log "=== 安装完成 ==="
	echo ""
	echo "✅ 安装完成！下一步："
	echo "  1. 激活环境:  source $VENV_DIR/bin/activate"
	echo "  2. 初始化配置:  deep-obsidian init <你的 vault 路径>"
	echo "  3. 导入笔记:  deep-obsidian ingest <vault 路径>"
	echo ""
	echo "完整日志: $LOG_FILE"
}

main "$@"
