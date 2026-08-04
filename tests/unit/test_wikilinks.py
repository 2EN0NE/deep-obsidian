"""Tests for wikilinks extractor — pure function, no Cognee dependency."""

from deep_obsidian.extractors.wikilinks import parse


class TestWikilinksSimple:
    def test_simple_wikilink(self):
        """[[target]] → single link with target as alias."""
        result = parse("See [[habit formation]] for details.")
        assert result == [{"target": "habit formation", "alias": "habit formation"}]

    def test_aliased_wikilink(self):
        """[[target|display text]] → target + alias separated."""
        result = parse("See [[Atomic Habits|the book]] for details.")
        assert result == [{"target": "Atomic Habits", "alias": "the book"}]

    def test_path_wikilink(self):
        """[[folder/note]] → target preserves path."""
        result = parse("Ref: [[Books/Learning/How to Study]]")
        assert result == [{"target": "Books/Learning/How to Study", "alias": "How to Study"}]

    def test_heading_anchor(self):
        """[[note#heading]] → target + anchor extracted."""
        result = parse("See [[habit#four steps]]")
        assert result == [{"target": "habit", "alias": "habit", "anchor": "four steps"}]

    def test_no_wikilinks(self):
        """Plain markdown without wikilinks → empty list."""
        result = parse("This is just a paragraph with **bold** text.")
        assert result == []

    def test_multiple_wikilinks(self):
        """Multiple [[links]] on one line all captured."""
        result = parse("From [[habit]] see also [[cue]] and [[reward]].")
        assert len(result) == 3
        assert result[0]["target"] == "habit"
        assert result[1]["target"] == "cue"
        assert result[2]["target"] == "reward"

    def test_empty_input(self):
        """Empty string → empty list."""
        assert parse("") == []
        assert parse("   \n  ") == []


class TestWikilinksEdgeCases:
    def test_code_block_ignored(self):
        """[[wikilinks]] inside inline code should be ignored."""
        result = parse("Here is `[[not a link]]` but [[real link]] is.")
        assert len(result) == 1
        assert result[0]["target"] == "real link"

    def test_fenced_code_block_ignored(self):
        """Wikilinks inside fenced code blocks should be ignored."""
        text = """Before
```markdown
[[ignore this]]
[[also ignore]]
```
After [[real link]]"""
        result = parse(text)
        assert len(result) == 1
        assert result[0]["target"] == "real link"

    def test_multiline_wikilink(self):
        """Wikilinks can span multiple content areas."""
        text = """---
tags: [habit]
---
# Title

[[first link]] is here. Then [[second|two]] follows.

[[third]] at the end."""
        result = parse(text)
        assert len(result) == 3
        targets = [r["target"] for r in result]
        assert "first link" in targets
        assert "second" in targets
        assert "third" in targets

    def test_chinese_wikilinks(self):
        """Chinese text in wikilinks preserved."""
        result = parse("参见 [[掌控习惯|这本书]] 了解更多")
        assert result == [{"target": "掌控习惯", "alias": "这本书"}]

    def test_empty_wikilink_brackets(self):
        """Empty [[]] brackets produce empty target."""
        result = parse("Here is [[]] an empty link.")
        assert result == [{"target": "", "alias": ""}]
