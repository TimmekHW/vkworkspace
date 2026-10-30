"""
Text formatting utilities for VK Teams Bot API.

Two approaches:

**1. String helpers** (``md`` / ``html``) — quick inline formatting::

    from vkworkspace.utils.text import md, html

    await message.answer(md.bold("Status"), parse_mode="MarkdownV2")
    await message.answer(html.bold("Status"), parse_mode="HTML")

**2. Text builder** (aiogram-style) — composable nodes with auto-escaping::

    from vkworkspace.utils.text import Text, Bold, Italic, Code

    content = Text("Hello, ", Bold("World"), "!")
    await message.answer(**content.as_kwargs())   # text + parse_mode auto

Nodes render through a *dialect* — the formatting rules of one VK Teams server
version (see :mod:`vkworkspace.formatting`). A style the dialect does not
support is rendered as plain text instead of markup.

.. warning::
    Do **not** mix string helpers with node builder::

        # WRONG — md.bold returns a raw string, gets double-escaped
        Text(md.bold("no"))

        # CORRECT — use node classes
        Text(Bold("yes"))
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import ClassVar, TypeVar

from vkworkspace.formatting.dialect import (
    DIALECT_ENV,
    DOCS_DIALECT,
    Dialect,
    DialectLike,
    get_dialect,
)

# ── MarkdownV2 ───────────────────────────────────────────────

_MD_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


class _Markdown:
    """MarkdownV2 formatting helpers.

    Usage::

        from vkworkspace.utils.text import md

        md.escape("price: 100$")     # "price: 100\\$"
        md.bold("important")         # "*important*"
        md.code("x = 1")            # "`x \\= 1`"
    """

    @staticmethod
    def escape(text: str) -> str:
        """Escape special MarkdownV2 characters.

        VK Teams requires this inside inline code and code blocks too: an
        unescaped ``_`` or ``-`` inside code is a «Format error», and a lone
        ``\\`` is consumed as an escape character.
        """
        return _MD_SPECIAL.sub(r"\\\1", text)

    @staticmethod
    def bold(text: str) -> str:
        return f"*{text}*"

    @staticmethod
    def italic(text: str) -> str:
        return f"_{text}_"

    @staticmethod
    def underline(text: str) -> str:
        return f"__{text}__"

    @staticmethod
    def strikethrough(text: str) -> str:
        return f"~{text}~"

    @staticmethod
    def code(text: str) -> str:
        """Inline code. *text* is raw — special characters are escaped here."""
        return f"`{_Markdown.escape(text)}`"

    @staticmethod
    def pre(text: str, language: str = "") -> str:
        """Code block. *text* is raw — special characters are escaped here."""
        body = _Markdown.escape(text)
        if language:
            return f"```{language}\n{body}\n```"
        return f"```\n{body}\n```"

    @staticmethod
    def link(text: str, url: str) -> str:
        return f"[{text}]({url})"

    @staticmethod
    def quote(text: str) -> str:
        lines = text.split("\n")
        return "\n".join(f">{line}" for line in lines)

    @staticmethod
    def mention(user_id: str) -> str:
        """Mention a user: ``@[user_id]`` with escaped content."""
        return f"@\\[{_Markdown.escape(user_id)}\\]"


# ── HTML ─────────────────────────────────────────────────────


class _HTML:
    """HTML formatting helpers.

    Usage::

        from vkworkspace.utils.text import html

        html.escape("1 < 2 & 3 > 0")   # "1 &lt; 2 &amp; 3 &gt; 0"
        html.bold("important")           # "<b>important</b>"
        html.code("x = 1")             # "<code>x = 1</code>"
    """

    @staticmethod
    def escape(text: str) -> str:
        """Escape ``<``, ``>``, ``&`` for HTML mode."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def bold(text: str) -> str:
        return f"<b>{text}</b>"

    @staticmethod
    def italic(text: str) -> str:
        return f"<i>{text}</i>"

    @staticmethod
    def underline(text: str) -> str:
        return f"<u>{text}</u>"

    @staticmethod
    def strikethrough(text: str) -> str:
        return f"<s>{text}</s>"

    @staticmethod
    def code(text: str) -> str:
        return f"<code>{text}</code>"

    @staticmethod
    def pre(text: str, language: str = "") -> str:
        if language:
            return f'<pre><code class="{language}">{text}</code></pre>'
        return f"<pre>{text}</pre>"

    @staticmethod
    def link(text: str, url: str) -> str:
        return f'<a href="{url}">{text}</a>'

    @staticmethod
    def quote(text: str) -> str:
        return f"<blockquote>{text}</blockquote>"

    @staticmethod
    def ordered_list(items: list[str]) -> str:
        li = "".join(f"<li>{item}</li>" for item in items)
        return f"<ol>{li}</ol>"

    @staticmethod
    def unordered_list(items: list[str]) -> str:
        li = "".join(f"<li>{item}</li>" for item in items)
        return f"<ul>{li}</ul>"

    @staticmethod
    def mention(user_id: str) -> str:
        """Mention a user: ``@[user_id]``."""
        return f"@[{user_id}]"


# ── Text Builder (aiogram-style composable nodes) ───────────


def _mode(parse_mode: str | None) -> str:
    """Dialect mode for a ``parse_mode`` value; ``None`` is plain text."""
    if parse_mode is None:
        return "plain"
    if str(parse_mode).lower() in ("markdownv2", "md"):
        return "markdownv2"
    return "html"


@dataclass(frozen=True, slots=True)
class _Ctx:
    """Render state: target mode, dialect, and the styles around the current node."""

    mode: str
    dialect: Dialect
    fixed: bool = False  # dialect set by the caller or a Text(dialect=...) above
    inside: frozenset[str] = frozenset()

    @classmethod
    def start(cls, mode: str, dialect: DialectLike | None) -> _Ctx:
        if dialect is not None:
            return cls(mode, get_dialect(dialect), fixed=True)
        return cls(mode, get_dialect(os.environ.get(DIALECT_ENV) or DOCS_DIALECT))

    def enter(self, style: str) -> _Ctx:
        return replace(self, inside=self.inside | {style})

    def native(self, style: str) -> bool:
        return self.dialect.native(style, self.mode, self.inside)

    def escape(self, text: str, where: str = "text") -> str:
        return self.dialect.escape(text, self.mode, where)

    def markup(self, key: str, **values: str) -> str:
        return self.dialect.markup(key, self.mode, **values)

    def fallback(self, key: str, **values: str) -> str:
        return self.dialect.fallback(key, self.mode, **values)


def _render_part(part: str | _Node, ctx: _Ctx) -> str:
    if isinstance(part, _Node):
        return part._render(ctx)
    return ctx.escape(str(part))


class _Node:
    """Base node for composable text formatting.

    Usage::

        from vkworkspace.utils.text import Text, Bold, Italic, Code

        content = Text("Hello, ", Bold("World"), "!")
        await message.answer(**content.as_kwargs())

    Nodes auto-escape plain strings — a backtick or ``*`` typed inside a string
    is literal text, not markup. Monospace is :class:`Code` / :class:`Pre`.
    Use :class:`Raw` for pre-formatted content.

    ``str(node)`` and f-strings render **HTML**; use :meth:`as_markdown` or
    :meth:`as_kwargs` for MarkdownV2.

    Every render method takes an optional *dialect* (name, ``.toml`` path or
    :class:`~vkworkspace.formatting.Dialect`). Without one, the nearest
    ``Text(dialect=...)`` above applies, then ``VKT_DIALECT``, then
    ``"vkteams-docs"`` — every style as markup.
    """

    def __init__(self, *parts: str | _Node) -> None:
        self._parts: tuple[str | _Node, ...] = parts

    # ── internal rendering ─────────────────────────────────

    def _plain(self) -> str:
        """Text content of the subtree with all formatting dropped."""
        return "".join(p._plain() if isinstance(p, _Node) else str(p) for p in self._parts)

    def _render_children(self, ctx: _Ctx) -> str:
        """Render children: escape strings, delegate nodes."""
        return "".join(_render_part(p, ctx) for p in self._parts)

    def _render(self, ctx: _Ctx) -> str:
        """Render this node.  Subclasses override to add wrappers."""
        return self._render_children(ctx)

    def _scope(self, ctx: _Ctx) -> _Ctx:
        """Context this node renders its children in."""
        return ctx

    def _with_parts(self, parts: Sequence[str | _Node]) -> _Node:
        """Copy of this node with other children (for :meth:`split`)."""
        clone = copy.copy(self)
        clone._parts = tuple(parts)
        return clone

    def _split_oversized(self, ctx: _Ctx, limit: int) -> list[_Node]:
        """Pieces of a node that renders longer than *limit*."""
        inner = self._scope(ctx)

        def make(parts: Sequence[str | _Node]) -> _Node:
            return self._with_parts(_trim(parts))

        return _pack(
            list(self._parts), make, ctx, limit, lambda p: _shrink(p, make, ctx, inner, limit)
        )

    # ── public API ─────────────────────────────────────────

    def as_html(self, dialect: DialectLike | None = None) -> str:
        """Render the entire tree as an HTML string."""
        return self._render(_Ctx.start("html", dialect))

    def as_markdown(self, dialect: DialectLike | None = None) -> str:
        """Render the entire tree as a MarkdownV2 string."""
        return self._render(_Ctx.start("markdownv2", dialect))

    def as_plain(self, dialect: DialectLike | None = None) -> str:
        """Render the entire tree as plain text, for ``parse_mode=None``.

        No markup and no escaping: links become ``text (url)``, list items get
        ``•`` / ``1.``, quote lines ``│``, mentions stay ``@[user_id]``. For the
        retry after a «Format error»::

            await message.answer(node.as_plain(), parse_mode=None)
        """
        return self._render(_Ctx.start("plain", dialect))

    def as_kwargs(
        self, parse_mode: str = "HTML", dialect: DialectLike | None = None
    ) -> dict[str, str]:
        """Return ``{"text": ..., "parse_mode": ...}`` ready for ``message.answer(**...)``.

        Usage::

            content = Text("Hello, ", Bold("World"))
            await message.answer(**content.as_kwargs())          # HTML (default)
            await message.answer(**content.as_kwargs("MarkdownV2"))  # MD
        """
        if _mode(parse_mode) == "markdownv2":
            return {"text": self.as_markdown(dialect), "parse_mode": "MarkdownV2"}
        return {"text": self.as_html(dialect), "parse_mode": "HTML"}

    def split(
        self,
        parse_mode: str | None = "HTML",
        max_length: int | None = None,
        *,
        dialect: DialectLike | None = None,
    ) -> list[Text]:
        """Split into parts that each render within *max_length* in *parse_mode*.

        Parts break between blocks and lines, never inside markup: a long code
        block becomes several blocks, a long list several lists. Length is
        counted in UTF-16 code units of the rendered text (markup included);
        *max_length* defaults to the dialect's ``max_length`` (4096).
        Render each part with the same *parse_mode*::

            for part in from_markdown(answer).split("MarkdownV2"):
                await message.answer(**part.as_kwargs("MarkdownV2"))
        """
        ctx = _Ctx.start(_mode(parse_mode), dialect)
        if isinstance(self, Text):
            ctx = self._scope(ctx)
        limit = max_length or ctx.dialect.max_length
        parts: list[Text] = []
        for piece in _split_part(self, ctx, limit):
            part = piece if isinstance(piece, Text) else Text(piece)
            parts.append(part if dialect is None else Text(part, dialect=dialect))
        return parts

    def __str__(self) -> str:
        return self.as_html()

    def __repr__(self) -> str:
        cls = type(self).__name__
        return f"{cls}({', '.join(repr(p) for p in self._parts)})"

    def __add__(self, other: str | _Node) -> Text:
        if isinstance(other, (str, _Node)):
            return Text(self, other)
        return NotImplemented

    def __radd__(self, other: str) -> Text:
        if isinstance(other, str):
            return Text(other, self)
        return NotImplemented


class Text(_Node):
    """Container — groups children without adding formatting.

    ::

        content = Text(
            "Price: ", Bold("$100"), "\\n",
            "Status: ", Italic("OK"),
        )
        await message.answer(**content.as_kwargs())

    ``Text(..., dialect="vkteams-25.4")`` binds the subtree to a dialect:
    it renders with that dialect unless the render call passes another one.
    """

    def __init__(self, *parts: str | _Node, dialect: DialectLike | None = None) -> None:
        super().__init__(*parts)
        self._dialect = dialect

    def _scope(self, ctx: _Ctx) -> _Ctx:
        if self._dialect is None or ctx.fixed:
            return ctx
        return replace(ctx, dialect=get_dialect(self._dialect), fixed=True)

    def _render(self, ctx: _Ctx) -> str:
        return self._render_children(self._scope(ctx))

    def __repr__(self) -> str:
        args = [repr(p) for p in self._parts]
        if self._dialect is not None:
            args.append(f"dialect={self._dialect!r}")
        return f"Text({', '.join(args)})"

    def __add__(self, other: str | _Node) -> Text:
        if isinstance(other, Text) and other._dialect in (None, self._dialect):
            return Text(*self._parts, *other._parts, dialect=self._dialect)
        if isinstance(other, (str, _Node)):
            return Text(*self._parts, other, dialect=self._dialect)
        return NotImplemented

    def __radd__(self, other: str) -> Text:
        if isinstance(other, str):
            return Text(other, *self._parts, dialect=self._dialect)
        return NotImplemented


class _Styled(_Node):
    """Node for one VK Teams style: markup where the dialect supports it, else fallback text."""

    _style: ClassVar[str]

    def _scope(self, ctx: _Ctx) -> _Ctx:
        return ctx.enter(self._style)

    def _render(self, ctx: _Ctx) -> str:
        if self._style in ctx.inside:
            # already in this style (e.g. a heading's bold around **bold**): just the content —
            # nested same-style markup (<b><b>…</b></b>) is a «Format error» in HTML
            return self._render_children(self._scope(ctx))
        if ctx.native(self._style):
            return self._native(ctx, self._scope(ctx))
        return self._fallback(ctx, self._scope(ctx))

    def _native(self, ctx: _Ctx, inner: _Ctx) -> str:
        return ctx.markup(self._style, text=self._render_children(inner))

    def _fallback(self, ctx: _Ctx, inner: _Ctx) -> str:
        return ctx.fallback(self._style, text=self._render_children(inner))


class Bold(_Styled):
    """Bold text: ``<b>...</b>`` / ``*...*``."""

    _style = "bold"


class Italic(_Styled):
    """Italic text: ``<i>...</i>`` / ``_..._``."""

    _style = "italic"


class Underline(_Styled):
    """Underlined text: ``<u>...</u>`` / ``__...__``."""

    _style = "underline"


class Strikethrough(_Styled):
    """Strikethrough text: ``<s>...</s>`` / ``~...~``."""

    _style = "strikethrough"


class Code(_Styled):
    """Inline code — content is literal (not recursively formatted).

    ``Code("x < 1")`` → ``<code>x &lt; 1</code>`` (HTML) / ```x < 1``` (MD).
    Special characters inside are escaped for MarkdownV2; nested nodes
    contribute their plain text (code cannot contain other styles).
    A dialect with ``[highlight] inline_code = "bold"`` wraps it in bold
    (``<b><code>x</code></b>``), except inside bold.
    """

    _style = "inline_code"

    def _native(self, ctx: _Ctx, inner: _Ctx) -> str:
        code = ctx.markup("inline_code", text=ctx.escape(self._plain(), "code"))
        wrap = ctx.dialect.code_highlight
        if wrap and wrap not in ctx.inside and ctx.native(wrap):
            return ctx.markup(wrap, text=code)
        return code

    def _fallback(self, ctx: _Ctx, inner: _Ctx) -> str:
        return ctx.fallback("inline_code", text=ctx.escape(self._plain()))

    def _split_oversized(self, ctx: _Ctx, limit: int) -> list[_Node]:
        return _shrink(self._plain(), self._with_parts, ctx, self._scope(ctx), limit)


class Pre(_Styled):
    """Code block with optional language.

    ::

        Pre("x = 42\\nprint(x)", language="python")

    Where a block is not allowed (inside a quote or a list), each line is
    rendered as inline code.
    """

    _style = "pre"

    def __init__(self, *parts: str | _Node, language: str = "") -> None:
        super().__init__(*parts)
        self._language = language

    def _native(self, ctx: _Ctx, inner: _Ctx) -> str:
        body = ctx.escape(self._plain(), "code")
        language = ctx.dialect.language(self._language, ctx.mode)
        if language and ctx.dialect.has_markup("pre_language", ctx.mode):
            return ctx.markup("pre_language", text=body, language=language)
        return ctx.markup("pre", text=body)

    def _fallback(self, ctx: _Ctx, inner: _Ctx) -> str:
        code = ctx.native("inline_code")
        lines = []
        for line in self._plain().split("\n"):
            if code and line.strip():
                lines.append(ctx.markup("inline_code", text=ctx.escape(line, "code")))
            else:
                lines.append(ctx.escape(line))
        return "\n".join(lines)

    def _split_oversized(self, ctx: _Ctx, limit: int) -> list[_Node]:
        def make(lines: Sequence[str | _Node]) -> _Node:
            return self._with_parts(["\n".join(str(line) for line in _trim(lines))])

        inner = self._scope(ctx)
        lines: list[str | _Node] = list(self._plain().split("\n"))
        return _pack(lines, make, ctx, limit, lambda p: _shrink(p, make, ctx, inner, limit))


class Link(_Styled):
    """Hyperlink: ``<a href="url">text</a>`` / ``[text](url)``.

    ::

        Link("Click here", url="https://example.com")
        Link(Bold("Important"), url="https://example.com")

    Without link support in the dialect: ``text (url)``, or just the URL when
    the text is the URL.
    """

    _style = "link"

    def __init__(self, text: str | _Node, url: str) -> None:
        super().__init__(text)
        self._url = url

    def _native(self, ctx: _Ctx, inner: _Ctx) -> str:
        return ctx.markup(
            "link", text=self._render_children(inner), url=ctx.escape(self._url, "url")
        )

    def _fallback(self, ctx: _Ctx, inner: _Ctx) -> str:
        shown = self._plain()
        if not shown or shown == self._url or self._url == f"mailto:{shown}":
            return ctx.escape(shown or self._url)
        return ctx.fallback("link", text=self._render_children(inner), url=ctx.escape(self._url))


class Mention(_Styled):
    """VK Teams user mention: ``@[user_id]``.

    ::

        Mention("user@company.ru")
    """

    _style = "mention"

    def __init__(self, user_id: str) -> None:
        super().__init__()
        self._user_id = user_id

    def _plain(self) -> str:
        return f"@[{self._user_id}]"

    def _native(self, ctx: _Ctx, inner: _Ctx) -> str:
        return ctx.markup("mention", id=ctx.escape(self._user_id))

    def _fallback(self, ctx: _Ctx, inner: _Ctx) -> str:
        return ctx.fallback("mention", id=ctx.escape(self._user_id))

    def _split_oversized(self, ctx: _Ctx, limit: int) -> list[_Node]:
        return [self]

    def __repr__(self) -> str:
        return f"Mention({self._user_id!r})"


class Quote(_Styled):
    """Block quote: ``<blockquote>...</blockquote>`` / ``>...``."""

    _style = "quote"


class _List(_Styled):
    _item: ClassVar[str]

    def __init__(self, *items: str | _Node, start: int = 1) -> None:
        super().__init__(*items)
        self._start = start

    def _render(self, ctx: _Ctx) -> str:
        if not self._parts:
            return ""
        inner = self._scope(ctx)
        items = [_render_part(part, inner) for part in self._parts]
        if ctx.native(self._style) and self._markup_fits(items):
            return self._as_markup(ctx, items)
        return self._as_text(ctx, items)

    def _markup_fits(self, items: list[str]) -> bool:
        """List markup is used for one-line items only."""
        return not any("\n" in item for item in items)

    def _as_markup(self, ctx: _Ctx, items: list[str]) -> str:
        body = ctx.dialect.list_separator(ctx.mode).join(
            ctx.markup(self._item, n=str(self._start + i), text=item)
            for i, item in enumerate(items)
        )
        return ctx.markup(self._style, items=body)

    def _as_text(self, ctx: _Ctx, items: list[str]) -> str:
        lines: list[str] = []
        for i, item in enumerate(items):
            n = str(self._start + i)
            first, *rest = item.split("\n")
            lines.append(ctx.fallback(self._item, n=n, text=first))
            indent = " " * len(ctx.dialect.fallback(self._item, "plain", n=n, text=""))
            lines.extend(indent + line if line else line for line in rest)
        return "\n".join(lines)

    def _split_oversized(self, ctx: _Ctx, limit: int) -> list[_Node]:
        inner = self._scope(ctx)

        def make(items: Sequence[tuple[int, str | _Node]]) -> _Node:
            clone = self._with_parts(_trim([part for _, part in items]))
            if isinstance(clone, _List) and items:
                clone._start = self._start + items[0][0]
            return clone

        def shrink(item: tuple[int, str | _Node]) -> list[_Node]:
            index, part = item
            return _shrink(part, lambda ps: make([(index, p) for p in ps]), ctx, inner, limit)

        return _pack(list(enumerate(self._parts)), make, ctx, limit, shrink)


class OrderedList(_List):
    """Numbered list, one item per argument: ``<ol><li>…</li></ol>`` / ``1. …``.

    ::

        OrderedList("first", Bold("second"), start=1)

    List markup is used when every item fits on one line and the list starts
    at 1; otherwise — and without list support in the dialect — ``1. item``
    lines of text.
    """

    _style = "ordered_list"
    _item = "ordered_item"

    def _markup_fits(self, items: list[str]) -> bool:
        return self._start == 1 and super()._markup_fits(items)


class UnorderedList(_List):
    """Bulleted list, one item per argument: ``<ul><li>…</li></ul>`` / ``- …``.

    ::

        UnorderedList("apples", "pears")

    List markup is used when every item fits on one line; otherwise — and
    without list support in the dialect — ``• item`` lines of text.
    """

    _style = "unordered_list"
    _item = "unordered_item"


class Raw(_Node):
    """Pre-rendered content — passed through **without** escaping.

    Use when you have already-formatted text::

        Raw(html.bold("Hello"))   # not escaped again

    .. warning::
        ``Raw`` bypasses escaping for *both* modes.  Only use when you
        control the target parse mode.
    """

    def _render(self, ctx: _Ctx) -> str:
        return "".join(str(p) for p in self._parts)

    def _split_oversized(self, ctx: _Ctx, limit: int) -> list[_Node]:
        return [self]


# ── split() helpers ──────────────────────────────────────────


def _width(text: str) -> int:
    """Length in UTF-16 code units (never less than ``len(text)``)."""
    return len(text.encode("utf-16-le")) // 2


def _fits(part: str | _Node, ctx: _Ctx, limit: int) -> bool:
    return _width(_render_part(part, ctx)) <= limit


def _trim(parts: Sequence[str | _Node]) -> list[str | _Node]:
    """*parts* without whitespace-only strings at both ends."""
    start, end = 0, len(parts)
    while start < end and isinstance(parts[start], str) and not str(parts[start]).strip():
        start += 1
    while end > start and isinstance(parts[end - 1], str) and not str(parts[end - 1]).strip():
        end -= 1
    return list(parts[start:end])


def _split_part(part: str | _Node, ctx: _Ctx, limit: int) -> list[str | _Node]:
    if _fits(part, ctx, limit):
        return [part]
    if isinstance(part, _Node):
        return list(part._split_oversized(ctx, limit))
    return list(_split_string(str(part), ctx, limit))


def _split_string(text: str, ctx: _Ctx, limit: int) -> list[str]:
    """Cut *text* so each escaped piece fits *limit*: at a newline, a space, or anywhere."""
    widths = [_width(ctx.escape(ch)) for ch in text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end, used = start, 0
        while end < len(text) and used + widths[end] <= limit:
            used += widths[end]
            end += 1
        if end == len(text):
            pieces.append(text[start:])
            break
        end = max(end, start + 1)
        cut = text.rfind("\n", start + 1, end + 1)
        if cut == -1:
            cut = text.rfind(" ", start + 1, end + 1)
        if cut == -1:
            pieces.append(text[start:end])
            start = end
        else:
            pieces.append(text[start:cut])
            start = cut + 1
    return pieces


def _shrink(
    part: str | _Node,
    make: Callable[[Sequence[str | _Node]], _Node],
    ctx: _Ctx,
    inner: _Ctx,
    limit: int,
) -> list[_Node]:
    """Split *part*, too long even alone, into pieces whose ``make([piece])`` fits *limit*."""
    budget = limit - _width(make([])._render(ctx))
    while True:
        made = [make([piece]) for piece in _split_part(part, inner, max(budget, 1))]
        if budget <= 1 or all(_fits(node, ctx, limit) for node in made):
            return made
        budget = min(budget - 1, budget * 9 // 10)


_T = TypeVar("_T")


def _pack(
    items: list[_T],
    make: Callable[[Sequence[_T]], _Node],
    ctx: _Ctx,
    limit: int,
    shrink: Callable[[_T], list[_Node]],
) -> list[_Node]:
    """Group *items* greedily into ``make(group)`` nodes that render within *limit*."""
    out: list[_Node] = []
    group: list[_T] = []
    for item in items:
        if _fits(make([*group, item]), ctx, limit):
            group.append(item)
            continue
        if group:
            out.append(make(group))
            group = []
            if _fits(make([item]), ctx, limit):
                group = [item]
                continue
        out.extend(shrink(item))
    if group:
        out.append(make(group))
    return out


# ── Singleton instances ──────────────────────────────────────

md = _Markdown()
html = _HTML()


# ── split_text ───────────────────────────────────────────────


def split_text(text: str, max_length: int = 4096) -> list[str]:
    """Split text into chunks of at most *max_length* characters.

    Tries to split on newlines first, then on spaces, then hard-cuts.
    For a formatted node use :meth:`Text.split` — it never cuts inside markup.

    Usage::

        from vkworkspace.utils.text import split_text

        for chunk in split_text(long_text):
            await message.answer(chunk)
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Try to split at last newline within limit
        cut = text.rfind("\n", 0, max_length)
        if cut == -1 or cut == 0:
            # Try to split at last space
            cut = text.rfind(" ", 0, max_length)
        if cut == -1 or cut == 0:
            # Hard cut
            cut = max_length

        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")

    return chunks
