"""Programmatic builder for the VK Teams ``format`` parameter.

The ``format`` parameter uses offset/length ranges to describe text formatting
without any markup syntax.  This builder makes it easy to construct the dict.

Usage::

    from vkworkspace.utils.format_builder import FormatBuilder

    fb = FormatBuilder("Hello, World! Click here.")
    fb.bold(0, 5)                               # "Hello" bold
    fb.italic(7, 6)                              # "World!" italic
    fb.link(14, 10, url="https://example.com")   # "Click here" as link

    await bot.send_text(chat_id, fb.text, format_=fb.build())

Or find substrings automatically::

    fb = FormatBuilder("Order #42 is ready! Visit https://shop.com")
    fb.bold_text("Order #42")
    fb.italic_text("ready")
    fb.link_text("https://shop.com", url="https://shop.com")

    await bot.send_text(chat_id, fb.text, format_=fb.build())
"""

from __future__ import annotations

from typing import Any


class FormatBuilder:
    """Build a ``format`` dict for VK Teams ``messages/sendText``.

    Each method adds one or more spans (offset + length) to the format dict.
    Call :meth:`build` to get the final dict ready for ``format_=``.
    """

    def __init__(self, text: str = "") -> None:
        """
        Args:
            text: The message text. Used by ``*_text()`` methods to find substrings.
        """
        self.text = text
        self._spans: dict[str, list[dict[str, Any]]] = {}

    def _add(self, style: str, offset: int, length: int, **extra: Any) -> FormatBuilder:
        span: dict[str, Any] = {"offset": offset, "length": length}
        span.update(extra)
        self._spans.setdefault(style, []).append(span)
        return self

    def _find_and_add(self, style: str, substring: str, **extra: Any) -> FormatBuilder:
        idx = self.text.find(substring)
        if idx == -1:
            raise ValueError(f"Substring {substring!r} not found in text")
        return self._add(style, idx, len(substring), **extra)

    # ── by offset/length ──────────────────────────────────────────
    #
    # Each method takes (offset, length) and returns self for chaining.
    # Example: fb.bold(0, 5).italic(7, 6)

    def bold(self, offset: int, length: int) -> FormatBuilder:
        """Make text **bold** at given offset/length."""
        return self._add("bold", offset, length)

    def italic(self, offset: int, length: int) -> FormatBuilder:
        """Make text *italic* at given offset/length."""
        return self._add("italic", offset, length)

    def underline(self, offset: int, length: int) -> FormatBuilder:
        """Underline text at given offset/length."""
        return self._add("underline", offset, length)

    def strikethrough(self, offset: int, length: int) -> FormatBuilder:
        """~~Strikethrough~~ text at given offset/length."""
        return self._add("strikethrough", offset, length)

    def link(self, offset: int, length: int, *, url: str) -> FormatBuilder:
        """Make text a clickable link at given offset/length."""
        return self._add("link", offset, length, url=url)

    def mention(self, offset: int, length: int) -> FormatBuilder:
        """Mark text as a @mention at given offset/length."""
        return self._add("mention", offset, length)

    def inline_code(self, offset: int, length: int) -> FormatBuilder:
        """Format text as ``inline code`` at given offset/length."""
        return self._add("inlineCode", offset, length)

    def pre(self, offset: int, length: int) -> FormatBuilder:
        """Format text as a code block at given offset/length."""
        return self._add("pre", offset, length)

    def ordered_list(self, offset: int, length: int) -> FormatBuilder:
        """Format text as an ordered list item at given offset/length."""
        return self._add("orderedList", offset, length)

    def unordered_list(self, offset: int, length: int) -> FormatBuilder:
        """Format text as an unordered list item at given offset/length."""
        return self._add("unorderedList", offset, length)

    def quote(self, offset: int, length: int) -> FormatBuilder:
        """Format text as a blockquote at given offset/length."""
        return self._add("quote", offset, length)

    # ── by substring (auto-find offset) ───────────────────────────
    #
    # Each *_text() method finds the substring in self.text
    # and applies formatting automatically.
    # Raises ValueError if substring is not found.

    def bold_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and make it **bold**."""
        return self._find_and_add("bold", substring)

    def italic_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and make it *italic*."""
        return self._find_and_add("italic", substring)

    def underline_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and underline it."""
        return self._find_and_add("underline", substring)

    def strikethrough_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and ~~strikethrough~~ it."""
        return self._find_and_add("strikethrough", substring)

    def link_text(self, substring: str, *, url: str) -> FormatBuilder:
        """Find *substring* in text and make it a clickable link."""
        return self._find_and_add("link", substring, url=url)

    def mention_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and mark it as a @mention."""
        return self._find_and_add("mention", substring)

    def inline_code_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and format as ``inline code``."""
        return self._find_and_add("inlineCode", substring)

    def pre_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and format as a code block."""
        return self._find_and_add("pre", substring)

    def quote_text(self, substring: str) -> FormatBuilder:
        """Find *substring* in text and format as a blockquote."""
        return self._find_and_add("quote", substring)

    # ── output ────────────────────────────────────────────────────

    def build(self) -> dict[str, list[dict[str, Any]]]:
        """Return the ``format`` dict ready for ``format_=``."""
        return {k: list(v) for k, v in self._spans.items()}
