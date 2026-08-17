"""Settings management — .deep-obsidian/settings.jsonc read/write.

JSONC (JSON with comments): parsed via ``json5``, written back with a
comment-preserving updater so hand-written comments survive edits.

三级配置层级（ADR-0014）：--config > 项目级 > 用户级，运行时深度 merge。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deep_obsidian._jsonc import atomic_write, deep_merge, load_jsonc, update_jsonc

SETTINGS_DIR = ".deep-obsidian"
SETTINGS_FILE = "settings.jsonc"
CLI_VERSION = "0.1.0"

# 配置层级（ADR-0014）：显式 > 项目级 > 用户级
LEVEL_CONFIG = "config"
LEVEL_PROJECT = "project"
LEVEL_USER = "user"

# Template body — first-time / --force writes use this (with values
# filled in by init_project).  ``update_settings`` preserves whatever
# is already on disk, including any comments the user added.
_TEMPLATE = """\
{
  // 此文件含 API key，勿提交 git
  "deep-obsidian-id": "{deep_obsidian_id}",
  "name": "{name}",
  "created_at": "{created_at}",
  "last_used_at": "{last_used_at}",
  "cli_version": "{cli_version}",

  // Cognee LLM 配置 → cognee.config.set_llm_config()
  "llm": {
    "provider": "openai",  // 可选: openai, custom, ollama
    "model": "openai/gpt-5-mini",
    "api_key": "",
    "endpoint": ""
  },

  // Cognee Embedding 配置 → cognee.config.set_embedding_config()
  "embedding": {
    "provider": "fastembed",
    "model": "BAAI/bge-small-en-v1.5",
    "dimensions": 384
  },

  // 非 Cognee 运行时环境变量（HuggingFace 等）→ os.environ 注入
  // 注意: hf_hub_offline 默认不预设（缺失 = 在线）。首次 ingest 需联网下载
  // embedding 模型（~100MB，缓存到 ~/.cache/huggingface/）；下载完成后
  // 如需完全离线，在此处显式设 true（或 init 交互向导中开启）。
  "network": {
    "hf_endpoint": "",
    "cognee_skip_connection_test": true
  }
}
"""


def find_project_root(path: str | Path) -> Path | None:
    """Walk up from path to find a directory containing .deep-obsidian/.

    A .deep-obsidian/ directory alone is not enough — Cognee may create
    one as a log fallback in e.g. $HOME/.deep-obsidian/.  The directory
    must also contain settings.jsonc, which is created by ``init``.

    Returns the project root, or None if no project is found.
    """
    current = Path(path).resolve()
    if not current.exists():
        return None

    for parent in [current, *current.parents]:
        settings_dir = parent / SETTINGS_DIR
        if settings_dir.is_dir() and (settings_dir / SETTINGS_FILE).is_file():
            return parent
    return None


def read_settings(project_root: str | Path) -> dict:
    """Read and parse the settings.jsonc in the project root."""
    settings_path = Path(project_root) / SETTINGS_DIR / SETTINGS_FILE
    if not settings_path.is_file():
        raise FileNotFoundError(
            f"Project settings not found at {settings_path}. Run 'deep-obsidian init' first."
        )
    return load_jsonc(settings_path.read_text(encoding="utf-8"))


def write_settings(project_root: str | Path, data: dict) -> None:
    """Write settings dict to the project's settings.jsonc (template-based).

    Writes the canonical JSONC template (with comments) and overlays
    ``data`` on top of it — values in ``data`` win, template defaults
    fill the rest.  Used by ``init_project`` for first-time / --force
    creation.  For surgical updates on an existing file, use
    ``update_settings`` instead.
    """
    settings_dir = Path(project_root) / SETTINGS_DIR
    settings_path = settings_dir / SETTINGS_FILE
    text = _format_settings(data)
    if data:
        text = update_jsonc(text, data)
    atomic_write(settings_path, text)


def update_settings(project_root: str | Path, updates: dict) -> dict:
    """Surgically update leaf values in settings.jsonc, preserving comments.

    ``updates`` is a nested dict of key paths → new values, e.g.
    ``{"llm": {"provider": "custom"}}``.  Only the matching leaf lines
    are rewritten; comments, indentation, and untouched keys survive
    verbatim (ADR-0011).  New keys are inserted into their parent block.

    Returns the merged settings dict (current + updates).
    """
    settings_path = Path(project_root) / SETTINGS_DIR / SETTINGS_FILE
    if not settings_path.is_file():
        raise FileNotFoundError(
            f"Project settings not found at {settings_path}. Run 'deep-obsidian init' first."
        )
    text = settings_path.read_text(encoding="utf-8")
    new_text = update_jsonc(text, updates)
    if new_text != text:
        atomic_write(settings_path, new_text)
    current = load_jsonc(new_text)
    deep_merge(current, updates)
    return current


# ── 配置层级解析（ADR-0014）──


def _user_settings_dir() -> Path:
    """User-level config dir — computed per call so HOME changes (tests)
    are respected.  Returns ~/.deep-obsidian."""
    return Path.home() / SETTINGS_DIR


def _vault_index_path(user_dir: Path) -> Path:
    """Path to the user-level vault registry (index.json)."""
    return user_dir / "vaults" / "index.json"


def load_vault_index(user_dir: str | Path) -> dict[str, dict]:
    """Load the vault registry (hash → {vault_path, dataset, updated_at}).

    Returns an empty dict when the index doesn't exist or is corrupt.
    """
    path = _vault_index_path(Path(user_dir))
    try:
        data = load_jsonc(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _save_vault_index(user_dir: Path, index: dict[str, dict]) -> None:
    """Atomically persist the vault registry."""
    atomic_write(_vault_index_path(user_dir), json.dumps(index, indent=2, ensure_ascii=False))


def register_vault(
    user_dir: str | Path,
    vault: str | Path,
    *,
    dataset: str | None = None,
) -> dict:
    """Register a vault under the user-level registry (idempotent).

    The key is the vault path hash; the entry records the resolved
    absolute path, dataset name, and update timestamp.  Returns the
    written entry.
    """
    from datetime import UTC, datetime

    user_dir_p = Path(user_dir)
    h = vault_path_hash(vault)
    entry = {
        "vault_path": str(Path(vault).resolve()),
        "dataset": dataset or Path(vault).name,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    index = load_vault_index(user_dir_p)
    index[h] = entry
    _save_vault_index(user_dir_p, index)
    return entry


def unregister_vault(user_dir: str | Path, vault: str | Path) -> bool:
    """Remove a vault from the registry.  Returns True if it was present."""
    user_dir_p = Path(user_dir)
    h = vault_path_hash(vault)
    index = load_vault_index(user_dir_p)
    if h not in index:
        return False
    del index[h]
    _save_vault_index(user_dir_p, index)
    return True


def vault_path_hash(vault: str | Path) -> str:
    """Return a stable 8-char hash of a vault's absolute path.

    Used to isolate per-vault state under the user-level config dir
    (~/.deep-obsidian/vaults/<hash>/).  Symlinks are resolved before
    hashing so two paths to the same vault share a slot.
    """
    resolved = str(Path(vault).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]


def hashes_path_for(vault: Path, config_dir: Path, level: str) -> Path:
    """Resolve where hashes.json lives for a vault (ADR-0014).

    - project/config level: ``<config_dir>/vault/hashes.json`` (one
      project = one vault, stored flat).
    - user level: ``<config_dir>/vaults/<vault_hash>/hashes.json``
      (multiple vaults share the user config, isolated by path hash).
    """
    if level == LEVEL_USER:
        return config_dir / "vaults" / vault_path_hash(vault) / "hashes.json"
    return config_dir / "vault" / "hashes.json"


@dataclass
class ResolvedConfig:
    """Result of :func:`resolve_config` — merged settings + placement info.

    Attributes:
        settings: 三级 merge 后的完整配置（深度 merge，非空才覆盖）。
        config_dir: 最个性化配置所在目录（.deep-obsidian/ 或 ~/.deep-obsidian）。
        level: LEVEL_CONFIG / LEVEL_PROJECT / LEVEL_USER。
        vault: 本次操作的工作空间（.cognee/ 挂这里）。
        hashes_path: 解析后的 hashes.json 位置。
    """

    settings: dict
    config_dir: Path
    level: str
    vault: Path
    hashes_path: Path

    def to_dict(self) -> dict:
        """Serialize for --json output / tests."""
        return {
            "settings": self.settings,
            "config_dir": str(self.config_dir),
            "level": self.level,
            "vault": str(self.vault),
            "hashes_path": str(self.hashes_path),
        }


def _merge_nonempty(base: dict, layer: dict) -> None:
    """Merge ``layer`` into ``base`` in place; non-empty values win.

    Depth-first: nested dicts merge recursively, scalars/lists replace
    only when the incoming value is non-empty (not None, not "", not
    empty list).  This is the "非空才覆盖" rule of ADR-0014 — a higher
    layer leaving a key empty inherits the lower layer's value.
    """
    for key, value in layer.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_nonempty(base[key], value)
        elif value not in (None, "", []):
            base[key] = value


def _merge_layers(*layers: dict | None) -> dict:
    """Deep-merge layers in order; later layers win on non-empty conflict.

    ``layers`` are ordered from lowest to highest priority (e.g. user,
    then project, then --config).  Empty/None layers are skipped.
    """
    merged: dict[str, Any] = {}
    for layer in layers:
        if not layer:
            continue
        _merge_nonempty(merged, layer)
    return merged


def resolve_config(
    *,
    vault: str | Path | None = None,
    config_path: str | Path | None = None,
    cwd: str | Path | None = None,
) -> ResolvedConfig:
    """Resolve the effective config for an operation (ADR-0014).

    Three-level lookup + deep merge, most-specific wins:

    - ``config_path`` (--config): used verbatim, no upward search.
    - project level: ``find_project_root(cwd)`` → .deep-obsidian/.
    - user level: ``~/.deep-obsidian/settings.jsonc`` (REQUIRED base
      layer — missing it raises RuntimeError).

    ``vault`` is the workspace being operated on (explicit from the
    caller, e.g. ingest's target); ``.cognee`` and hashes placement
    derive from it.  Defaults to ``cwd``.
    """
    cwd_path = Path(cwd or Path.cwd())
    # vault 显式给出时，项目级配置从 vault 向上找（用户在别处操作已知
    # 工作空间）；vault 未给出时从 cwd 找。
    vault_path = Path(vault).resolve() if vault else cwd_path.resolve()
    # 单文件目标（ingest 传单个 .md）：工作空间取其所在目录 —— rel 路径、
    # .cognee/ 与 hashes 都挂在目录上，与整库入库的命名空间一致
    # （回归：曾把文件本身当 vault，导致 hashes 键退化为 "." 且
    # .cognee/ 被指向文件路径之下）。
    if vault is not None and vault_path.is_file():
        vault_path = vault_path.parent
    search_start = vault_path if vault else cwd_path

    # 用户级：必需基础层
    user_dir = _user_settings_dir()
    user_settings_path = user_dir / SETTINGS_FILE
    if not user_settings_path.is_file():
        # 注意：CLI 没有 `init --user` 标志——用户级基础层只能通过交互式
        # init（层级选 2）或非交互 init（缺省兼建）创建，文案必须指向真实
        # 可执行的命令，否则用户按提示操作会撞上 "No such option"。
        raise RuntimeError(
            "用户级配置缺失：未找到 ~/.deep-obsidian/settings.jsonc。"
            "请先运行 'deep-obsidian init <vault路径>' 创建"
            "（首次 init 会自动兼建用户级配置）。"
        )
    user_settings = load_jsonc(user_settings_path.read_text(encoding="utf-8"))

    # 项目级：从操作目标（vault 或 cwd）向上找
    project_root = find_project_root(search_start)
    project_settings: dict | None = None
    if project_root is not None:
        project_settings = read_settings(project_root)

    # --config 显式指定
    explicit_settings: dict | None = None
    if config_path is not None:
        explicit_settings = load_jsonc(Path(config_path).read_text(encoding="utf-8"))

    settings = _merge_layers(user_settings, project_settings, explicit_settings)

    if explicit_settings is not None:
        assert config_path is not None  # explicit_settings implies config_path
        level = LEVEL_CONFIG
        config_dir = Path(config_path).resolve().parent
    elif project_root is not None:
        level = LEVEL_PROJECT
        config_dir = project_root / SETTINGS_DIR
    else:
        level = LEVEL_USER
        config_dir = user_dir

    return ResolvedConfig(
        settings=settings,
        config_dir=config_dir,
        level=level,
        vault=vault_path,
        hashes_path=hashes_path_for(vault_path, config_dir, level),
    )


def init_project(
    path: str | Path,
    name: str | None = None,
    *,
    force: bool = False,
    level: str = LEVEL_PROJECT,
) -> dict:
    """Initialize a new project at path.

    Creates settings.jsonc with default values.  ``level`` selects the
    config tier (ADR-0014):

    - ``LEVEL_PROJECT`` (default): <path>/.deep-obsidian/settings.jsonc.
    - ``LEVEL_USER``: ~/.deep-obsidian/settings.jsonc (machine-wide
      base layer — every vault merges on top of it).

    If settings already exist at the target tier, returns them without
    overwriting unless ``force=True``.

    When ``force=True``, removes stale state from a previous run — the
    tier's own settings dir and the vault's ``.cognee/`` — before
    re-creating the project from scratch.  This is the "factory reset"
    path.

    The user-level directory ``~/.deep-obsidian/`` is NEVER touched by a
    project-level force: it is the machine-wide base layer (ADR-0014,
    required by every vault) and holds the vault registry plus other
    vaults' user-level hashes.  Only a user-level ``force`` (where the
    tier's settings dir *is* ``~/.deep-obsidian``) resets it.
    """
    import shutil

    root = Path(path).resolve()
    settings_dir = root / SETTINGS_DIR if level == LEVEL_PROJECT else _user_settings_dir()
    settings_path = settings_dir / SETTINGS_FILE

    if force:
        for _dir, _label in [
            (settings_dir, "settings dir"),
            (root / ".cognee", "vault .cognee/"),
        ]:
            try:
                if _dir.exists():
                    shutil.rmtree(_dir)
            except OSError:
                pass  # locked / permissions — continue, not fatal
    elif settings_path.is_file():
        return load_jsonc(settings_path.read_text(encoding="utf-8"))

    now = datetime.now(UTC).isoformat()
    data: dict[str, Any] = {
        "deep-obsidian-id": str(uuid.uuid4()),
        "name": name or root.name,
        "created_at": now,
        "last_used_at": now,
        "cli_version": CLI_VERSION,
        "llm": {
            "provider": "openai",
            "model": "openai/gpt-5-mini",
            "api_key": "",
            "endpoint": "",
        },
        "embedding": {
            "provider": "fastembed",
            "model": "BAAI/bge-small-en-v1.5",
            "dimensions": 384,
        },
        "network": {
            "hf_endpoint": "",
            "cognee_skip_connection_test": True,
        },
    }
    write_settings(Path.home() if level == LEVEL_USER else root, data)
    return data


def _format_settings(data: dict) -> str:
    """Serialize a settings dict into the canonical JSONC template."""
    values = {
        "deep_obsidian_id": data.get("deep-obsidian-id", ""),
        "name": data.get("name", ""),
        "created_at": data.get("created_at", ""),
        "last_used_at": data.get("last_used_at", ""),
        "cli_version": data.get("cli_version", CLI_VERSION),
    }

    # 一次性替换全部占位符：若逐键 replace，先替换进去的值（如 name 含
    # "{created_at}" 字面量）会被后续替换误伤。re.sub 只遍历原始文本，
    # 替换结果不再递归匹配。
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        return str(values.get(key, m.group(0)))

    return re.sub(r"\{(\w+)\}", _sub, _TEMPLATE)
