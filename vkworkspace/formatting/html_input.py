"""HTML (the way bots and LLMs write it for VK Teams) → text nodes.

Tags VK Teams has become their nodes; ``<br>`` is a line break; ``<p>``,
``<div>`` and headings (bold) are lines of their own; a table becomes a
monospace block; any other tag keeps only its text. In text outside
``<code>`` / ``<pre>``, GFM code — ```` ```block``` ````, ```` ```line``` ````,
`` `inline` `` — becomes code and ``@[user_id]`` a mention.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from vkworkspace.formatting._common import RULE, mentions, table_block, url_as_text
from vkworkspace.formatting.dialect import Dialect, DialectLike, get_dialect
from vkworkspace.utils.text import (
    Bold,
    Code,
    Italic,
    Link,
    OrderedList,
    Pre,
    Quote,
    Strikethrough,
    Text,
    Underline,
    UnorderedList,
    _Node,
    _trim,
)

_TAG_RE = re.compile(
    r"<!--.*?-->|</?([A-Za-z][A-Za-z0-9]*)(?:\s(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)?/?>",
    re.DOTALL,
)
_CODE_RE = re.compile(
    r"(?<!\\)```(?P<lang>[^\n`]*)\n(?P<block>.*?)\n?```"
    r"|(?<!\\)```(?P<line>[^\n`]+)```"
    r"|(?<!\\)`(?P<inline>[^`\n]+)`",
    re.DOTALL,
)
_INLINE: dict[str, type[_Node]] = {
    "b": Bold,
    "strong": Bold,
    "i": Italic,
    "em": Italic,
    "u": Underline,
    "ins": Underline,
    "s": Strikethrough,
    "strike": Strikethrough,
    "del": Strikethrough,
}
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_DROPPED = frozenset({"script", "style", "head", "title"})
_LITERAL = frozenset({"code", "pre"})
_KNOWN = frozenset(
    {
        *_INLINE, *_HEADINGS, *_DROPPED, *_LITERAL,
        "a", "abbr", "article", "big", "blockquote", "br", "center", "cite", "dd", "details",
        "div", "dl", "dt", "font", "footer", "header", "hr", "html", "body", "img", "kbd",
        "li", "main", "mark", "nav", "ol", "p", "q", "samp", "section", "small", "span",
        "sub", "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "tt",
        "ul", "var", "wbr",
    }
)  # fmt: skip


def convert(text: str, dialect: DialectLike | None = None) -> Text:
    """HTML *text* → a :class:`Text` tree bound to *dialect*."""
    resolved = get_dialect(dialect)
    parser = _Parser(resolved)
    parser.feed(_protect(text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")))
    parser.close()
    return Text(*parser.result(), dialect=resolved)


def _protect(text: str) -> str:
    """Escape every ``<`` that does not open a known tag — the parser would drop such text."""
    out: list[str] = []
    pos = 0
    for match in _TAG_RE.finditer(text):
        name = match.group(1)
        if name is not None and name.lower() not in _KNOWN:
            continue
        out.append(text[pos : match.start()].replace("<", "&lt;"))
        out.append(match.group(0))
        pos = match.end()
    out.append(text[pos:].replace("<", "&lt;"))
    return "".join(out)


def _islands(text: str) -> list[str | _Node]:
    """GFM code and ``@[user_id]`` mentions in a run of text."""
    out: list[str | _Node] = []
    pos = 0
    for match in _CODE_RE.finditer(text):
        out.extend(mentions(text[pos : match.start()]))
        if match.group("block") is not None:
            info = match.group("lang").split()
            out.append(Pre(match.group("block"), language=info[0] if info else ""))
        else:
            out.append(Code(match.group("line") or match.group("inline")))
        pos = match.end()
    out.extend(mentions(text[pos:]))
    return out


def _language(css_class: str) -> str:
    for name in css_class.split():
        return name.removeprefix("language-").removeprefix("lang-")
    return ""


class _Item(Text):
    """A ``<li>``."""


class _Cell(Text):
    """A ``<td>`` / ``<th>``."""

    def __init__(self, *parts: str | _Node, align: str = "") -> None:
        super().__init__(*parts)
        self.align = align


class _Row(Text):
    """A ``<tr>``."""

    def __init__(self, cells: list[_Cell]) -> None:
        super().__init__(*cells)
        self.cells = cells


class _Element:
    __slots__ = ("attrs", "need_break", "parts", "tag")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parts: list[str | _Node] = []
        self.need_break = False  # the next content starts on a new line


class _Parser(HTMLParser):
    def __init__(self, dialect: Dialect) -> None:
        super().__init__(convert_charrefs=True)
        self.dialect = dialect
        self.stack = [_Element("", {})]

    # ── parser events ──────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag in ("br", "wbr"):
            self.add("\n" if tag == "br" else "")
        elif tag == "hr":
            self.add(Text(RULE), block=True)
        elif tag == "img":
            alt, src = values.get("alt", ""), values.get("src", "")
            self.add(Link(Text(alt), url=src) if src and not url_as_text(alt, src) else alt or src)
        else:
            self.stack.append(_Element(tag, values))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "wbr", "hr", "img"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if all(element.tag != tag for element in self.stack[1:]):
            return
        while True:
            element = self.stack.pop()
            self.close_element(element)
            if element.tag == tag:
                return

    def handle_data(self, data: str) -> None:
        self.add(data)

    def result(self) -> list[str | _Node]:
        while len(self.stack) > 1:
            self.close_element(self.stack.pop())
        return _trim(self.finish(self.stack[0]))

    # ── building ───────────────────────────────────────────

    def add(self, part: str | _Node, *, block: bool = False) -> None:
        parent = self.stack[-1]
        if isinstance(part, str) and not part.strip():
            if part and not parent.need_break:
                parent.parts.append(part)
            return
        starts_line = isinstance(part, str) and part.startswith("\n")
        if (
            parent.parts
            and (block or parent.need_break)
            and not starts_line
            and not _ends_with_newline(parent.parts)
        ):
            parent.parts.append("\n")
        parent.parts.append(part)
        parent.need_break = block

    def finish(self, element: _Element) -> list[str | _Node]:
        """Children with adjacent strings merged and, outside code, code islands found."""
        merged: list[str | _Node] = []
        for part in element.parts:
            if isinstance(part, str) and merged and isinstance(merged[-1], str):
                merged[-1] = str(merged[-1]) + part
            else:
                merged.append(part)
        if element.tag in _LITERAL or any(e.tag in _LITERAL for e in self.stack):
            return merged
        out: list[str | _Node] = []
        for part in merged:
            out.extend(_islands(part) if isinstance(part, str) else [part])
        return out

    def close_element(self, element: _Element) -> None:
        tag = element.tag
        if tag in _DROPPED:
            return
        parts = self.finish(element)
        if tag in _INLINE:
            self.add(_INLINE[tag](*parts))
        elif tag == "a" and element.attrs.get("href"):
            href, shown = element.attrs["href"], Text(*parts)._plain()
            self.add(shown or href if url_as_text(shown, href) else Link(Text(*parts), url=href))
        elif tag == "code":
            if self.stack[-1].tag == "pre":
                self.stack[-1].attrs.setdefault(
                    "language", _language(element.attrs.get("class", ""))
                )
            self.add(Code(*parts))
        elif tag == "pre":
            body = Text(*parts)._plain().removeprefix("\n").removesuffix("\n")
            language = element.attrs.get("language") or _language(element.attrs.get("class", ""))
            self.add(Pre(body, language=language), block=True)
        elif tag in ("ul", "ol"):
            self.add(_list(tag, element, parts), block=True)
        elif tag == "li":
            self.add(_Item(*_trim(parts)), block=True)
        elif tag in ("td", "th"):
            align = element.attrs.get("align", "") or _style_align(element.attrs.get("style", ""))
            self.add(_Cell(*_trim(parts), align=align))
        elif tag == "tr":
            self.add(_Row([part for part in parts if isinstance(part, _Cell)]), block=True)
        elif tag == "table":
            self.add(self.table(parts), block=True)
        else:
            self.close_block(tag, parts)

    def close_block(self, tag: str, parts: list[str | _Node]) -> None:
        if tag == "blockquote":
            self.add(Quote(*_trim(parts)), block=True)
        elif tag in _HEADINGS:
            self.add(Bold(*_trim(parts)), block=True)
        elif tag in ("p", "div", "dl", "dt", "dd", "details", "summary", "section", "article"):
            self.add(Text(*_trim(parts)), block=True)
        else:  # any other tag keeps its content
            for part in parts:
                self.add(part)

    def table(self, parts: list[str | _Node]) -> _Node:
        rows = [part for part in parts if isinstance(part, _Row) and part.cells]
        if not rows:
            return Text(*parts)
        return table_block(
            [
                [cell.as_plain(self.dialect).replace("\n", " ") for cell in row.cells]
                for row in rows
            ],
            [cell.align for cell in rows[0].cells],
        )


def _list(tag: str, element: _Element, parts: list[str | _Node]) -> _Node:
    items = [part if isinstance(part, _Item) else Text(part) for part in _trim(parts)]
    items = [item for item in items if not (isinstance(item, Text) and not item._plain().strip())]
    if tag == "ul":
        return UnorderedList(*items)
    try:
        start = int(element.attrs.get("start") or 1)
    except ValueError:
        start = 1
    return OrderedList(*items, start=start)


def _style_align(style: str) -> str:
    match = re.search(r"text-align\s*:\s*(left|right|center)", style)
    return match.group(1) if match else ""


def _ends_with_newline(parts: list[str | _Node]) -> bool:
    last = parts[-1]
    text = last if isinstance(last, str) else last._plain()
    return text.endswith("\n")
