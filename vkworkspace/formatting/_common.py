"""Pieces shared by the Markdown and HTML converters."""

from __future__ import annotations

import re
import unicodedata

from vkworkspace.utils.text import Mention, Pre, _Node

MENTION_RE = re.compile(r"@\[([^\s\[\]]+)\]")
RULE = "———"


def mentions(text: str) -> list[str | _Node]:
    """*text* with every ``@[user_id]`` as a :class:`Mention`."""
    parts: list[str | _Node] = []
    pos = 0
    for match in MENTION_RE.finditer(text):
        if match.start() > pos:
            parts.append(text[pos : match.start()])
        parts.append(Mention(match.group(1)))
        pos = match.end()
    if pos < len(text):
        parts.append(text[pos:])
    return parts


def url_as_text(shown: str, url: str) -> bool:
    """A link that shows its own URL (or nothing) goes as plain text; clients linkify URLs."""
    return not shown or shown == url or url == f"mailto:{shown}"


def table_block(rows: list[list[str]], aligns: list[str]) -> Pre:
    """Table rows (first row — the header) → a monospace block with aligned columns.

    *aligns*: ``"left"`` / ``"right"`` / ``"center"`` / ``""`` per column.
    """
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    aligns = aligns + [""] * (columns - len(aligns))
    widths = [max(_display_width(row[i]) for row in rows) for i in range(columns)]

    def line(row: list[str]) -> str:
        cells = (_pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row))
        return " │ ".join(cells).rstrip()

    rule = "─┼─".join("─" * width for width in widths)
    return Pre("\n".join([line(rows[0]), rule, *(line(row) for row in rows[1:])]))


def _display_width(text: str) -> int:
    return sum(
        0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        for ch in text
    )


def _pad(text: str, width: int, align: str) -> str:
    space = width - _display_width(text)
    if align == "right":
        return " " * space + text
    if align == "center":
        return " " * (space // 2) + text + " " * (space - space // 2)
    return text + " " * space
