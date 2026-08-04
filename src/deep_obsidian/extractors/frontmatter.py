"""Parse YAML frontmatter from Markdown text — pure function."""

import re

import yaml

# Matches ``---`` at the start of a line (opening or closing delimiter).
_FM_DELIM = re.compile(r"^---", re.MULTILINE)


def parse(text: str) -> dict:
    """Extract YAML frontmatter from markdown text.

    Frontmatter is a YAML block delimited by --- on its own line,
    appearing at the very beginning of the document.

    Returns a dict of the parsed YAML, or empty dict if:
        - No frontmatter found
        - Malformed YAML
        - Frontmatter is empty
    """
    text = text.lstrip()  # strip leading whitespace including \r\n
    if not text.startswith("---"):
        return {}

    # Find closing --- on its own line
    rest = text[3:]  # after opening ---
    m = _FM_DELIM.search(rest)
    if m is None:
        return {}  # no closing delimiter

    yaml_str = rest[: m.start()].strip()
    if not yaml_str:
        return {}

    try:
        result = yaml.safe_load(yaml_str)
        if isinstance(result, dict):
            return result
        return {}
    except yaml.YAMLError:
        return {}
