"""Markdown (CommonMark + GFM tables / strikethrough) → text nodes.

Parsed with markdown-it-py. Headings become bold, tables a monospace block,
``@[user_id]`` a mention; raw HTML in the input stays text.
"""

from __future__ import annotations

import re
from functools import lru_cache

try:
    from markdown_it import MarkdownIt
    from markdown_it.rules_inline import StateInline
    from markdown_it.tree import SyntaxTreeNode
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise ImportError(
        'from_markdown needs markdown-it-py: pip install "vkworkspace[markdown]"'
    ) from exc

from vkworkspace.formatting._common import MENTION_RE, RULE, table_block, url_as_text
from vkworkspace.formatting.dialect import Dialect, DialectLike, get_dialect
from vkworkspace.utils.text import (
    Bold,
    Code,
    Italic,
    Link,
    Mention,
    OrderedList,
    Pre,
    Quote,
    Strikethrough,
    Text,
    UnorderedList,
    _Node,
)

_BLANK_RE = re.compile(r"[\s>]*")  # a blank line, also inside a quote
_WRAPPERS: dict[str, type[_Node]] = {"strong": Bold, "em": Italic, "s": Strikethrough}


def _mention_rule(state: StateInline, silent: bool) -> bool:
    """``@[user_id]`` → a ``vk_mention`` token (before links, so ``[id]`` is never a link)."""
    match = MENTION_RE.match(state.src, state.pos)
    if match is None:
        return False
    if not silent:
        token = state.push("vk_mention", "", 0)
        token.content = match.group(1)
    state.pos = match.end()
    return True


@lru_cache(maxsize=1)
def _parser() -> MarkdownIt:
    parser = MarkdownIt("commonmark", options_update={"html": False})
    parser.enable(["table", "strikethrough"])
    parser.inline.ruler.before("link", "vk_mention", _mention_rule)
    return parser


def convert(text: str, dialect: DialectLike | None = None) -> Text:
    """Markdown *text* → a :class:`Text` tree bound to *dialect*."""
    resolved = get_dialect(dialect)
    source = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    tree = SyntaxTreeNode(_parser().parse(source))
    converter = _Converter(resolved, source.split("\n"))
    return Text(*converter.blocks(tree.children), dialect=resolved)


class _Converter:
    def __init__(self, dialect: Dialect, lines: list[str]) -> None:
        self.dialect = dialect
        self.lines = lines

    def blocks(self, nodes: list[SyntaxTreeNode]) -> list[str | _Node]:
        """Block nodes, separated as in the source: a blank line or a line break."""
        out: list[str | _Node] = []
        for node in nodes:
            block = self.block(node)
            if block is None:
                continue
            if out:
                out.append("\n\n" if self.blank_before(node) else "\n")
            out.append(block)
        return out

    def blank_before(self, node: SyntaxTreeNode) -> bool:
        if node.map is None or node.map[0] == 0:
            return True
        return _BLANK_RE.fullmatch(self.lines[node.map[0] - 1]) is not None

    def block(self, node: SyntaxTreeNode) -> _Node | None:
        kind = node.type
        if kind == "paragraph":
            return Text(*self.inline_of(node))
        if kind == "heading":
            return Bold(*self.inline_of(node))
        if kind == "blockquote":
            return Quote(*self.blocks(node.children))
        if kind == "bullet_list":
            return UnorderedList(*(self.item(child) for child in node.children))
        if kind == "ordered_list":
            start = node.attrs.get("start", 1)
            items = (self.item(child) for child in node.children)
            return OrderedList(*items, start=int(start))
        if kind in ("fence", "code_block"):
            language = node.info.split()[0] if node.info.strip() else ""
            return Pre(node.content.removesuffix("\n"), language=language)
        if kind == "hr":
            return Text(RULE)
        if kind == "table":
            return self.table(node)
        return Text(node.content) if node.content else None

    def item(self, node: SyntaxTreeNode) -> Text:
        return Text(*self.blocks(node.children))

    def inline_of(self, node: SyntaxTreeNode) -> list[str | _Node]:
        parts: list[str | _Node] = []
        for child in node.children:
            parts.extend(self.inline(child) if child.type == "inline" else [])
        return parts

    def inline(self, node: SyntaxTreeNode) -> list[str | _Node]:
        out: list[str | _Node] = []
        for child in node.children:
            kind = child.type
            if kind in _WRAPPERS:
                out.append(_WRAPPERS[kind](*self.inline(child)))
            elif kind in ("link", "image"):
                url = str(child.attrs["href" if kind == "link" else "src"])
                label = Text(*self.inline(child))
                if child.markup == "autolink" or url_as_text(label._plain(), url):
                    out.append(label._plain() or url)
                else:
                    out.append(Link(label, url=url))
            elif kind in ("softbreak", "hardbreak"):
                out.append("\n")
            elif kind == "code_inline":
                out.append(Code(child.content))
            elif kind == "vk_mention":
                out.append(Mention(child.content))
            elif child.content:
                out.append(child.content)
        return out

    def table(self, node: SyntaxTreeNode) -> Pre:
        """GFM table → a monospace block with aligned columns."""
        rows: list[list[str]] = []
        aligns: list[str] = []
        for section in node.children:
            for row in section.children:
                if section.type == "thead":
                    aligns = [_align(cell) for cell in row.children]
                rows.append([self.cell(cell) for cell in row.children])
        return table_block(rows, aligns)

    def cell(self, node: SyntaxTreeNode) -> str:
        return Text(*self.inline_of(node)).as_plain(self.dialect).replace("\n", " ")


def _align(cell: SyntaxTreeNode) -> str:
    style = str(cell.attrs.get("style", ""))
    return style.removeprefix("text-align:")
