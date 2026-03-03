from __future__ import annotations

import pytest

from vkworkspace.utils.format_builder import FormatBuilder


class TestFormatBuilderBasic:
    def test_bold_offset(self) -> None:
        fb = FormatBuilder("Hello")
        fb.bold(0, 5)
        assert fb.build() == {"bold": [{"offset": 0, "length": 5}]}

    def test_chaining(self) -> None:
        fb = FormatBuilder("Hello World")
        result = fb.bold(0, 5).italic(6, 5).build()
        assert "bold" in result
        assert "italic" in result

    def test_bold_text_auto_find(self) -> None:
        fb = FormatBuilder("Hello World")
        fb.bold_text("Hello")
        assert fb.build() == {"bold": [{"offset": 0, "length": 5}]}

    def test_link_with_url(self) -> None:
        fb = FormatBuilder("Click here!")
        fb.link(0, 10, url="https://example.com")
        result = fb.build()
        assert result["link"][0]["url"] == "https://example.com"

    def test_link_text_with_url(self) -> None:
        fb = FormatBuilder("Visit https://example.com today")
        fb.link_text("https://example.com", url="https://example.com")
        result = fb.build()
        assert result["link"][0]["offset"] == 6
        assert result["link"][0]["length"] == 19

    def test_substring_not_found(self) -> None:
        fb = FormatBuilder("Hello")
        with pytest.raises(ValueError, match="not found"):
            fb.bold_text("missing")

    def test_all_styles(self) -> None:
        text = "a b c d e f g h i j k"
        fb = FormatBuilder(text)
        fb.bold(0, 1)
        fb.italic(2, 1)
        fb.underline(4, 1)
        fb.strikethrough(6, 1)
        fb.link(8, 1, url="https://x.com")
        fb.mention(10, 1)
        fb.inline_code(12, 1)
        fb.pre(14, 1)
        fb.ordered_list(16, 1)
        fb.unordered_list(18, 1)
        fb.quote(20, 1)
        result = fb.build()
        assert len(result) == 11

    def test_empty_build(self) -> None:
        fb = FormatBuilder("Hello")
        assert fb.build() == {}


class TestFormatBuilderValidation:
    def test_same_style_overlap_raises(self) -> None:
        fb = FormatBuilder("Hello World")
        fb.bold(0, 6)
        fb.bold(3, 5)
        with pytest.raises(ValueError, match="Overlapping 'bold'"):
            fb.build()

    def test_same_style_no_overlap_ok(self) -> None:
        fb = FormatBuilder("Hello World")
        fb.bold(0, 5)
        fb.bold(6, 5)
        fb.build()  # no error

    def test_same_style_adjacent_ok(self) -> None:
        fb = FormatBuilder("Hello World")
        fb.bold(0, 5)
        fb.bold(5, 6)  # adjacent, not overlapping
        fb.build()  # no error

    def test_pre_conflicts_with_bold(self) -> None:
        fb = FormatBuilder("Hello World")
        fb.pre(0, 11)
        fb.bold(0, 5)
        with pytest.raises(ValueError, match="Conflicting styles"):
            fb.build()

    def test_pre_conflicts_with_italic(self) -> None:
        fb = FormatBuilder("Hello World")
        fb.pre(0, 5)
        fb.italic(3, 5)
        with pytest.raises(ValueError, match="Conflicting styles"):
            fb.build()

    def test_pre_conflicts_with_inline_code(self) -> None:
        fb = FormatBuilder("Hello World")
        fb.pre(0, 11)
        fb.inline_code(0, 5)
        with pytest.raises(ValueError, match="Conflicting styles"):
            fb.build()

    def test_link_conflicts_with_mention(self) -> None:
        fb = FormatBuilder("@user link")
        fb.link(0, 5, url="https://x.com")
        fb.mention(0, 5)
        with pytest.raises(ValueError, match="Conflicting styles"):
            fb.build()

    def test_ordered_conflicts_with_unordered(self) -> None:
        fb = FormatBuilder("item one")
        fb.ordered_list(0, 8)
        fb.unordered_list(0, 8)
        with pytest.raises(ValueError, match="Conflicting styles"):
            fb.build()

    def test_ordered_conflicts_with_quote(self) -> None:
        fb = FormatBuilder("item one")
        fb.ordered_list(0, 8)
        fb.quote(0, 8)
        with pytest.raises(ValueError, match="Conflicting styles"):
            fb.build()

    def test_non_overlapping_conflicts_ok(self) -> None:
        fb = FormatBuilder("Hello World Code")
        fb.bold(0, 5)
        fb.pre(12, 4)  # non-overlapping — ok
        fb.build()  # no error

    def test_bold_italic_same_range_ok(self) -> None:
        fb = FormatBuilder("Hello")
        fb.bold(0, 5)
        fb.italic(0, 5)  # bold+italic is allowed
        fb.build()  # no error

    def test_validate_callable_separately(self) -> None:
        fb = FormatBuilder("Hello")
        fb.pre(0, 5)
        fb.bold(0, 5)
        with pytest.raises(ValueError):
            fb.validate()
