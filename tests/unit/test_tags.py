"""Tests for tags extractor — pure function, no Cognee dependency."""

from deep_obsidian.extractors.tags import parse


class TestTagsBasic:
    def test_frontmatter_tags_list(self):
        """Tags from frontmatter tags: as list."""
        text = """---
tags: [habit, psychology, self-improvement]
---
# Content"""
        result = parse(text)
        assert result == ["habit", "psychology", "self-improvement"]

    def test_frontmatter_tags_single(self):
        """Tags from frontmatter tags: as single string."""
        text = """---
tags: habit
---
Content"""
        result = parse(text)
        assert result == ["habit"]

    def test_inline_tags(self):
        """#tags in body text extracted."""
        text = """# Title
This is about #habit and #productivity."""
        result = parse(text)
        assert "habit" in result
        assert "productivity" in result

    def test_combined_tags(self):
        """Frontmatter tags + inline tags merged and deduplicated."""
        text = """---
tags: [habit, psychology]
---
#habit helps with #psychology daily."""
        result = parse(text)
        assert sorted(result) == ["habit", "psychology"]

    def test_no_tags(self):
        """No tags anywhere → empty list."""
        text = "# Just a title\nSome content without tags."
        result = parse(text)
        assert result == []


class TestTagsEdgeCases:
    def test_tags_in_code_ignored(self):
        """#tags inside inline code ignored."""
        text = "Use `#not-a-tag` but #real-tag is here."
        result = parse(text)
        assert result == ["real-tag"]

    def test_tags_in_fenced_code_ignored(self):
        """#tags inside fenced code blocks ignored."""
        text = """---
tags: [habit]
---
# Title
```python
# This is a comment, not a tag
```
#real-tag after code."""
        result = parse(text)
        assert sorted(result) == ["habit", "real-tag"]

    def test_chinese_tags(self):
        """Chinese tags are supported."""
        text = """---
tags: [习惯, 心理学]
---
#学习 is inline."""
        result = parse(text)
        assert "习惯" in result
        assert "心理学" in result
        assert "学习" in result

    def test_frontmatter_tags_yaml_list(self):
        """Tags with YAML block list syntax."""
        text = """---
tags:
  - habit
  - psychology
  - self-improvement
---
Content"""
        result = parse(text)
        assert result == ["habit", "psychology", "self-improvement"]

    def test_empty_tags(self):
        """Empty tags field → empty list."""
        text = """---
tags: []
---
Content #mytag"""
        result = parse(text)
        assert result == ["mytag"]

    def test_tag_with_cjk_and_digits(self):
        """Tags with CJK characters and digits."""
        text = "#2024目标"
        result = parse(text)
        assert result == ["2024目标"]
