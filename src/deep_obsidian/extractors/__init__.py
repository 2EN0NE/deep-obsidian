"""Markdown structure extractors — pure functions, zero Cognee dependency.

Pipelines:
    wikilinks: parse [[wikilinks]] and [[aliased|links]] from markdown body
    frontmatter: parse YAML frontmatter (between --- delimiters)
    tags: extract Obsidian tags from frontmatter or inline #tags
"""
