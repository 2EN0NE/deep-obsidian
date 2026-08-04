"""Extract [[wikilinks]] from Markdown text — pure function."""

import re

# Match [[target]] or [[target|alias]] or [[target#anchor]] or [[target#anchor|alias]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]*?)(?:#([^\]|]*?))?(?:\|([^\]]*?))?\]\]")


def parse(text: str) -> list[dict]:
    """Extract all [[wikilinks]] from markdown text.

    Returns a list of dicts with keys:
        target: the link target (file name without brackets)
        alias: display text (same as target if no |alias)
        anchor: heading anchor if #anchor present (optional)

    Ignores wikilinks inside inline code (`` `[[...]]` ``) and
    fenced code blocks (``` ... ```).
    """
    # Strip fenced code blocks
    clean = re.sub(r"```[\s\S]*?```", "", text)
    # Strip inline code spans
    clean = re.sub(r"`[^`]*?`", "", clean)

    links = []
    for m in _WIKILINK_RE.finditer(clean):
        target = m.group(1).strip()
        anchor = m.group(2).strip() if m.group(2) else None
        alias = m.group(3).strip() if m.group(3) else None

        if alias is None:
            # Use last path component as alias
            alias = target.rsplit("/", 1)[-1] if "/" in target else target

        entry = {"target": target, "alias": alias}
        if anchor:
            entry["anchor"] = anchor
        links.append(entry)

    return links
