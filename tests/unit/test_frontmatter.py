"""Tests for frontmatter extractor — pure function, no Cognee dependency."""

from deep_obsidian.extractors.frontmatter import parse


class TestFrontmatterBasic:
    def test_standard_frontmatter(self):
        """Standard YAML frontmatter between --- delimiters."""
        text = """---
title: My Note
tags: [habit, psychology]
date: 2024-06-11
---
# Content starts here"""
        result = parse(text)
        assert result["title"] == "My Note"
        assert result["tags"] == ["habit", "psychology"]
        from datetime import date

        assert result["date"] == date(2024, 6, 11)

    def test_no_frontmatter(self):
        """Markdown without frontmatter → empty dict."""
        text = """# Just a title
Some content here."""
        result = parse(text)
        assert result == {}

    def test_empty_frontmatter(self):
        """Empty frontmatter block → empty dict."""
        text = """---
---
# Content"""
        result = parse(text)
        assert result == {}

    def test_frontmatter_without_closing(self):
        """Opening --- without closing → treated as horizontal rule, no frontmatter."""
        text = """---
This is content with a horizontal rule."""
        result = parse(text)
        assert result == {}

    def test_single_key_frontmatter(self):
        """Minimal frontmatter with one key."""
        text = """---
aliases: [alias1, alias2]
---
Content"""
        result = parse(text)
        assert result["aliases"] == ["alias1", "alias2"]


class TestFrontmatterEdgeCases:
    def test_nested_frontmatter(self):
        """Nested YAML structures preserved."""
        text = """---
metadata:
  author: James Clear
  year: 2018
  tags:
    - habit
    - self-improvement
---
# The Book"""
        result = parse(text)
        assert result["metadata"]["author"] == "James Clear"
        assert result["metadata"]["tags"] == ["habit", "self-improvement"]

    def test_malformed_yaml(self):
        """Malformed YAML returns empty dict gracefully."""
        text = """---
title: "unclosed quote
tags: [broken
---
Content"""
        result = parse(text)
        assert result == {}

    def test_boolean_number_values(self):
        """YAML booleans and numbers typed correctly."""
        text = """---
draft: true
priority: 1
rating: 4.5
---
Content"""
        result = parse(text)
        assert result["draft"] is True
        assert result["priority"] == 1
        assert result["rating"] == 4.5

    def test_frontmatter_with_extra_dashes_in_content(self):
        """Only first --- pair is frontmatter, later --- is content."""
        text = """---
title: Note
---
# Section
---
Another section"""
        result = parse(text)
        assert result == {"title": "Note"}

    def test_chinese_frontmatter(self):
        """Chinese text in frontmatter preserved."""
        text = """---
title: 掌控习惯
作者: 詹姆斯·克利尔
tags: [习惯, 心理学]
---
内容"""
        result = parse(text)
        assert result["title"] == "掌控习惯"
        assert result["tags"] == ["习惯", "心理学"]
