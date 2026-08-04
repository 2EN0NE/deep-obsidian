"""Extract Obsidian tags from Markdown — pure function.

Merges tags from:
    1. Frontmatter ``tags:`` field (list, single string, or YAML block)
    2. Inline #tags in body text

Returns a deduplicated list.
"""

import re

from deep_obsidian.extractors.frontmatter import parse as parse_frontmatter

# Match #tag patterns in body text — word characters, CJK, digits, underscores
_INLINE_TAG_RE = re.compile(r"#([\w\u4e00-\u9fff-]+)")


def parse(text: str) -> list[str]:
    """Extract all tags from markdown, merging frontmatter + inline.

    Returns a deduplicated, order-preserving list.
    """
    tags: list[str] = []

    # Frontmatter tags
    fm = parse_frontmatter(text)
    raw_tags = fm.get("tags")
    if raw_tags is not None:
        if isinstance(raw_tags, list):
            for t in raw_tags:
                tags.append(str(t))
        else:
            tags.append(str(raw_tags))

    # Strip fenced code blocks and inline code from body before matching
    body = text
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"`[^`]*?`", "", body)

    for m in _INLINE_TAG_RE.finditer(body):
        tag = m.group(1)
        if tag not in tags:
            tags.append(tag)

    # Remove None/empty strings
    return [t for t in tags if t]
