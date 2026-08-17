"""JSONC (JSON with comments) utilities — comment-preserving value updates.

The ``json5`` package parses JSONC into dicts but cannot serialize back
while preserving comments.  For ``settings.jsonc`` we need to update a
few leaf values without destroying the user's hand-written comments and
unrelated fields.  This module implements a minimal comment-aware
updater:

- ``load_jsonc(text)`` — parse JSONC (wraps ``json5.loads``).
- ``update_jsonc(text, updates)`` — return new text where the leaf
  values in ``updates`` (a nested dict of key paths) are replaced
  in-place; everything else (comments, indentation, untouched keys)
  is preserved verbatim.

Only object-key/leaf-value updates are supported (no array
manipulation, no key deletion).  New keys are inserted into their
parent object block, preserving that block's existing style.

The updater works on the raw text, not an AST: it scans line by line,
tracking the current object nesting level and key path, and rewrites
only the specific lines whose key path matches a target.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import json5

# A key line: optional indent, "key":, then the value (which may be a
# scalar, an opening brace for a nested object, or an inline object).
# We split into: indent, key, value-part (rest of line up to any trailing
# comment / comma).
_KEY_LINE = re.compile(r'^(\s*)"([^"]+)"\s*:\s*(.*)$')

# A block-closing brace line, optionally with a trailing comma and/or
# // comment — e.g. ``}``, ``},``, ``}, // llm 段结束``.  Must be matched
# BEFORE a key line would (it can't — closing braces never start with a
# quote) and tolerate user-written trailing comments, otherwise the
# nesting stack desyncs and later keys get wrong paths.
_CLOSE_BRACE = re.compile(r"^}\s*,?\s*(//.*)?$")


def _is_block_close(stripped: str) -> bool:
    return bool(_CLOSE_BRACE.match(stripped))


def load_jsonc(text: str) -> dict:
    """Parse JSONC text into a dict (comments ignored)."""
    return json5.loads(text)


def _parse_value(value_text: str) -> tuple[str, str]:
    """Split a key-line value part into (value, tail).

    ``tail`` is everything after the value (comma, trailing comment).
    The value itself may be quoted, a number, true/false/null, or an
    opening ``{``/``[`` (nested object/array).

    Both ``//`` and ``/* ... */`` trailing comments are recognised —
    otherwise a ``/* */`` comment after a rewritten value would be
    silently dropped (the scanner treats it as part of the value),
    violating the "everything else is preserved verbatim" contract.
    """
    value_text = value_text.strip()
    if not value_text:
        return "", ""
    if value_text[0] in "{[":
        return value_text[0], value_text[1:]
    # Scalar: match up to a comma or the start of a comment,
    # honoring string quotes.
    i = 0
    in_str = False
    while i < len(value_text):
        c = value_text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == ",":
            break
        elif c == "/" and i + 1 < len(value_text):
            # 引号外的 "/" 只可能是注释起始（JSONC 中裸斜杠非法）——
            # "//" 与 "/*" 都算注释开始。value 截止到斜杠，注释前的
            # 空格归入 tail，改写行才能逐字保留（"v" /* c */ → 不丢空格）。
            nxt = value_text[i + 1]
            if nxt == "/" or nxt == "*":
                while i > 0 and value_text[i - 1] == " ":
                    i -= 1
                break
        i += 1
    return value_text[:i], value_text[i:]


def _tail_has_closing_brace(tail: str) -> bool:
    """True if the rest of the line (after an opening ``{``) contains the
    matching closing ``}`` — i.e. the object is a single-line inline object.

    Quote-aware (brackets inside strings are ignored) and nesting-aware
    (``{ "a": { "b": 1 } }`` counts depth).  ``//`` comments are treated
    as inert text — a bracket inside a comment can mislead, but that falls
    through to the loud ``_verify_updates`` net.
    """
    depth = 1
    in_str = False
    i = 0
    while i < len(tail):
        c = tail[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return True
        i += 1
    return False


def _skip_array(lines: list[str], line_idx: int, tail: str) -> int:
    """Skip the array opened on ``lines[line_idx]``; return the index of
    the line after its closing ``]``.

    ``tail`` is the rest of the opening line after ``[`` (the array may
    close on that same line).  Quote-aware and nesting-aware, so brackets
    inside string values (``["a[0]", "b]c"]``) do not confuse the depth
    count.  Raises ValueError if the document ends before the array
    closes — the scanner cannot safely continue, and silently
    miss-skipping would corrupt later keys' paths (regression: a
    single-line array used to swallow the rest of the document, making
    updates land as duplicate keys).
    """
    depth = 1
    text = tail
    i = line_idx
    pos = 0
    while True:
        while pos < len(text):
            c = text[pos]
            if c == '"':
                pos += 1
                while pos < len(text):
                    if text[pos] == "\\":
                        pos += 2
                        continue
                    if text[pos] == '"':
                        break
                    pos += 1
                pos += 1
                continue
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return i + 1
            pos += 1
        i += 1
        if i >= len(lines):
            raise ValueError(
                "无法安全更新配置键：文件中存在未闭合的数组或括号内含字符串/"
                "注释的非常规写法。请将该数组展开为多行或调整写法后重试。"
            )
        text = lines[i]
        pos = 0


def _quote_value(value: Any) -> str:
    """Serialize a scalar Python value as a JSON literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False)


def update_jsonc(text: str, updates: dict) -> str:
    """Return ``text`` with leaf values from ``updates`` replaced.

    ``updates`` is a nested dict mapping key paths to new values, e.g.
    ``{"llm": {"provider": "custom", "model": "gpt-4o"}}``.  Only the
    matching leaf lines are rewritten; all other lines (comments,
    indentation, untouched keys) are preserved verbatim.
    """
    # Normalize updates into a flat map of key path tuples → value.
    targets: dict[tuple[str, ...], Any] = {}
    _flatten(updates, (), targets)

    lines = text.splitlines(keepends=True)
    # Track nesting: stack of (key, line_index_of_obj_open) where the
    # object was opened.  The stack holds the key path of the current
    # object scope.
    stack: list[tuple[str, ...]] = []
    out_lines = list(lines)
    # For "add new key" we track each object block's line span.
    # Block map: key_path (tuple) → (open_line_idx, close_line_idx, indent,
    # is_inline_or_array) — the flag marks single-line inline objects and
    # arrays, which cannot be safely rewritten/inserted into; targets under
    # them must fail loudly instead of silently duplicating keys.
    blocks: dict[tuple[str, ...], tuple[int, int, str, bool]] = {}
    pending_targets = dict(targets)
    key_idx: list[tuple[str, ...]] = []  # paths seen, in order

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            # Comment or blank line — skip, but a closing brace may follow.
            i += 1
            continue

        m = _KEY_LINE.match(line)
        if m:
            indent, key, rest = m.group(1), m.group(2), m.group(3)
            value, tail = _parse_value(rest)
            current_path: tuple[str, ...] = sum(stack, ()) + (key,)
            key_idx.append(current_path)

            if value == "{":
                if _tail_has_closing_brace(tail):
                    # 单行内联对象（{ ... } 同一行）：不透明叶子，不扫描
                    # 内部、不压栈。记入 blocks，使落在其下的目标键大声
                    # 失败（无法安全改写/插入）。
                    blocks[current_path] = (i, i, indent, True)
                else:
                    # 多行对象 —— push scope。
                    stack.append(current_path)
                    blocks[current_path] = (i, i, indent, False)
            elif value == "[":
                # 数组：整体跳过（含同尾行的闭合括号）。数组内容绝不能
                # 进入键路径栈 —— 其中的 "key": value 行会污染后续键的
                # 路径（回归：单行数组曾吞掉整个文档，更新静默落成重复
                # 键并丢失兄弟字段）。数组值本身不在支持范围内，记入
                # blocks（inline 标记）使针对数组键的更新大声失败。
                next_idx = _skip_array(lines, i, tail)
                blocks[current_path] = (i, next_idx - 1, indent, True)
                i = next_idx
                continue
            elif current_path in pending_targets:
                # Replace the scalar value, keep tail (comma/comment) and
                # the original line ending.
                new_val = _quote_value(pending_targets.pop(current_path))
                line_end = ""
                if line.endswith("\r\n"):
                    line_end = "\r\n"
                elif line.endswith("\n"):
                    line_end = "\n"
                new_line = f'{indent}"{key}": {new_val}{tail.rstrip()}{line_end}'
                out_lines[i] = new_line
        elif _is_block_close(stripped):
            # Closing a block (tolerating trailing comma / // comment).
            if stack:
                path = stack.pop()
                if path in blocks:
                    _open, _close, _ind, _inline = blocks[path]
                    blocks[path] = (_open, i, _ind, _inline)
        i += 1

    # 重复键路径 = 扫描器失步或文件本身含重复键 —— 两种情况下继续写入
    # 都可能产生与用户意图不符的结果，大声失败。
    if len(key_idx) != len(set(key_idx)):
        raise ValueError(
            "无法安全更新配置键：文件包含重复的键或无法解析的括号/注释写法。"
            "请检查 settings.jsonc 后重试。"
        )

    # Insert any remaining (unmatched) targets into their parent blocks.
    if pending_targets:
        out_lines = _insert_pending(out_lines, blocks, pending_targets, targets)

    new_text = "".join(out_lines)
    _verify_updates(new_text, targets)
    return new_text


def _verify_updates(text: str, targets: dict[tuple[str, ...], Any]) -> None:
    """Re-parse the produced JSONC and confirm every target leaf landed.

    The line scanner is deliberately best-effort — single-line inline
    objects (``"llm": {...}`` on one line), closing braces with trailing
    comments, and arrays whose contents contain brackets inside strings
    are all handled imperfectly.  Any silent miss must fail loudly here
    instead of writing a config file that does not reflect the caller's
    requested update (e.g. the interactive wizard "saving" an API key
    that never reached disk).
    """
    try:
        parsed = json5.loads(text)
    except Exception as exc:
        raise ValueError(
            "更新后的配置文件无法解析，已放弃写入。请检查 settings.jsonc 中"
            '是否含有单行内联对象（如 "llm": {...} 写在一行）或其他非常规写法。'
        ) from exc
    for path, expected in targets.items():
        node = parsed
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise ValueError(
                    "无法安全更新配置键 "
                    + ".".join(path)
                    + "：文件包含不被支持的单行内联对象或括号写法。"
                    "请将该键展开为多行（每个字段一行）后重试。"
                )
            node = node[key]
        if node != expected:
            raise ValueError(
                "配置键 " + ".".join(path) + " 更新后校验失败（磁盘值与期望不符），已放弃写入。"
                '常见原因：单行内联对象（如 "llm": {...} 写在一行）——'
                "请将该键展开为多行（每个字段一行）后重试。"
            )


def _flatten(updates: dict, prefix: tuple[str, ...], out: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict):
            _flatten(value, prefix + (key,), out)
        else:
            out[prefix + (key,)] = value


def _insert_pending(
    lines: list[str],
    blocks: dict[tuple[str, ...], tuple[int, int, str, bool]],
    pending: dict[tuple[str, ...], Any],
    targets: dict[tuple[str, ...], Any],
) -> list[str]:
    """Insert keys that had no matching line into their parent object block.

    For each pending key path (e.g. ``("network", "hf_endpoint")``) we
    find the deepest existing ancestor block (e.g. the document root),
    then insert the whole missing subtree (``network`` containing
    ``hf_endpoint``) before that block's closing brace, using the
    block's indent + 2 spaces.
    """
    out = list(lines)

    # Group pending by their nearest existing ancestor block.  If no
    # ancestor block exists for a path, it goes to the document root.
    by_parent: dict[tuple[str, ...], list[tuple[tuple[str, ...], Any]]] = {}
    for path, value in pending.items():
        # 目标路径经过单行内联对象/数组（无法安全改写或插入其内部）→
        # 大声失败。宁可不写，也不写一份与用户意图不符的配置。
        for depth in range(len(path), 0, -1):
            cand = path[:depth]
            if cand in blocks and blocks[cand][3]:
                raise ValueError(
                    "无法安全更新配置键 "
                    + ".".join(path)
                    + "：文件包含不被支持的单行内联对象或括号写法。"
                    "请将该键展开为多行（每个字段一行）后重试。"
                )
        # Find deepest existing ancestor: try path[:-1], path[:-2], ...
        ancestor = None
        for depth in range(len(path) - 1, 0, -1):
            candidate = path[:depth]
            if candidate in blocks:
                ancestor = candidate
                break
        key = path if ancestor is None else path[len(ancestor) :]
        by_parent.setdefault(ancestor if ancestor is not None else (), []).append((key, value))

    # For each parent, find insertion point.
    for parent, entries in by_parent.items():
        if parent in blocks:
            _open, close_idx, indent, _inline = blocks[parent]
            insert_at = close_idx
            child_indent = indent + "  "
        else:
            # Document root — insert before final closing brace.
            insert_at = _find_document_close(out)
            child_indent = "  "

        # Build ONE subtree per parent: merge sibling leaves that share
        # the same missing ancestor into a single nested object, then
        # serialize it once (avoids duplicate keys).
        merged: dict = {}
        for key_path, value in entries:
            node: Any = value
            for k in reversed(key_path):
                node = {k: node}
            deep_merge(merged, node)

        insert_lines: list[str] = []
        for top_key, top_value in merged.items():
            serialized = _serialize_subtree(top_key, top_value, child_indent)
            insert_lines.extend(ln + "\n" for ln in serialized)
            insert_lines[-1] = insert_lines[-1].rstrip() + ",\n"

        if insert_at >= len(out):
            out.extend(insert_lines)
        else:
            # Ensure the previous field (if any) ends with a comma so the
            # inserted block is valid JSONC.
            _ensure_prev_comma(out, insert_at)
            out[insert_at:insert_at] = insert_lines
    return out


def deep_merge(base: dict, update: dict) -> None:
    """Merge ``update`` into ``base`` in place (nested dicts merge)."""
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value


def _serialize_subtree(key: str, value: Any, indent: str) -> list[str]:
    """Serialize ``"key": <value>`` as re-indented lines, without an
    extra wrapping brace around the key itself.

    The value is serialized with 2-space nesting; its lines are shifted
    so the opening brace sits at ``indent`` and nested lines follow the
    existing indentation style.
    """
    inner = json.dumps(value, ensure_ascii=False, indent=2)
    inner_lines = inner.splitlines()
    # Line 0 is the opening brace; the remaining lines are already
    # indented by 2 relative to it — re-base them onto ``indent``.
    out: list[str] = [f'{indent}"{key}": {inner_lines[0]}']
    out.extend(indent + ln if ln else ln for ln in inner_lines[1:])
    return out


def _ensure_prev_comma(lines: list[str], insert_at: int) -> None:
    """If the last non-blank/non-comment line before ``insert_at`` is a
    field or closing brace without a trailing comma, append one (needed
    when inserting into a block whose previous last field had no comma).
    """
    for idx in range(insert_at - 1, -1, -1):
        s = lines[idx].strip()
        if not s or s.startswith("//") or s.startswith("/*"):
            continue
        if s.endswith(",") or s in ("{", "["):
            return
        # A field line or closing brace without comma — append one.
        lines[idx] = lines[idx].rstrip() + "," + ("\n" if lines[idx].endswith("\n") else "")
        return


def _find_document_close(lines: list[str]) -> int:
    """Find the index of the document's final closing brace."""
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip() == "}":
            return idx
    return len(lines)


def atomic_write(path: Path, text: str) -> None:
    """Atomically write text to path (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
