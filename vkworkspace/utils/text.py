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

.. warning::
    Do **not** mix string helpers with node builder::

        # WRONG — md.bold returns a raw string, gets double-escaped
        Text(md.bold("no"))

        # CORRECT — use node classes
        Text(Bold("yes"))
"""

from __future__ import annotations

import re

# ── MarkdownV2 ───────────────────────────────────────────────

_MD_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


class _Markdown:
    """MarkdownV2 formatting helpers.

    Usage::

        from vkworkspace.utils.text import md

        md.escape("price: 100$")     # "price: 100\\$"
        md.bold("important")         # "*important*"
        md.code("x = 1")            # "`x = 1`"
    """

    @staticmethod
    def escape(text: str) -> str:
        """Escape special MarkdownV2 characters."""
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
        return f"`{text}`"

    @staticmethod
    def pre(text: str, language: str = "") -> str:
        if language:
            return f"```{language}\n{text}\n```"
        return f"```\n{text}\n```"

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


def _escape_for_mode(text: str, mode: str) -> str:
    """Escape *text* for the given rendering mode (``html`` or ``md``)."""
    if mode == "html":
        return _HTML.escape(text)
    return _Markdown.escape(text)


class _Node:
    """Base node for composable text formatting.

    Usage::

        from vkworkspace.utils.text import Text, Bold, Italic, Code

        content = Text("Hello, ", Bold("World"), "!")
        await message.answer(**content.as_kwargs())

    Nodes auto-escape plain strings.  Use :class:`Raw` for pre-formatted content.
    """

    def __init__(self, *parts: str | _Node) -> None:
        self._parts: tuple[str | _Node, ...] = parts

    # ── internal rendering ─────────────────────────────────

    def _render_children(self, mode: str) -> str:
        """Render children: escape strings, delegate nodes."""
        buf: list[str] = []
        for p in self._parts:
            if isinstance(p, _Node):
                buf.append(p._to_str(mode))
            elif isinstance(p, str):
                buf.append(_escape_for_mode(p, mode))
            else:
                buf.append(_escape_for_mode(str(p), mode))
        return "".join(buf)

    def _to_str(self, mode: str) -> str:
        """Render this node.  Subclasses override to add wrappers."""
        return self._render_children(mode)

    # ── public API ─────────────────────────────────────────

    def as_html(self) -> str:
        """Render the entire tree as an HTML string."""
        return self._to_str("html")

    def as_markdown(self) -> str:
        """Render the entire tree as a MarkdownV2 string."""
        return self._to_str("md")

    def as_kwargs(self, parse_mode: str = "HTML") -> dict[str, str]:
        """Return ``{"text": ..., "parse_mode": ...}`` ready for ``message.answer(**...)``.

        Usage::

            content = Text("Hello, ", Bold("World"))
            await message.answer(**content.as_kwargs())          # HTML (default)
            await message.answer(**content.as_kwargs("MarkdownV2"))  # MD
        """
        if parse_mode in ("MarkdownV2", "md"):
            return {"text": self.as_markdown(), "parse_mode": "MarkdownV2"}
        return {"text": self.as_html(), "parse_mode": "HTML"}

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
    """

    def __add__(self, other: str | _Node) -> Text:
        if isinstance(other, Text):
            return Text(*self._parts, *other._parts)
        if isinstance(other, (str, _Node)):
            return Text(*self._parts, other)
        return NotImplemented

    def __radd__(self, other: str) -> Text:
        if isinstance(other, str):
            return Text(other, *self._parts)
        return NotImplemented


class Bold(_Node):
    """Bold text: ``<b>...</b>`` / ``*...*``."""

    def _to_str(self, mode: str) -> str:
        inner = self._render_children(mode)
        if mode == "html":
            return f"<b>{inner}</b>"
        return f"*{inner}*"


class Italic(_Node):
    """Italic text: ``<i>...</i>`` / ``_..._``."""

    def _to_str(self, mode: str) -> str:
        inner = self._render_children(mode)
        if mode == "html":
            return f"<i>{inner}</i>"
        return f"_{inner}_"


class Underline(_Node):
    """Underlined text: ``<u>...</u>`` / ``__...__``."""

    def _to_str(self, mode: str) -> str:
        inner = self._render_children(mode)
        if mode == "html":
            return f"<u>{inner}</u>"
        return f"__{inner}__"


class Strikethrough(_Node):
    """Strikethrough text: ``<s>...</s>`` / ``~...~``."""

    def _to_str(self, mode: str) -> str:
        inner = self._render_children(mode)
        if mode == "html":
            return f"<s>{inner}</s>"
        return f"~{inner}~"


class Code(_Node):
    """Inline code — content is literal (not recursively formatted).

    ``Code("x < 1")`` → ``<code>x &lt; 1</code>`` (HTML) / ```x < 1``` (MD).
    """

    def _to_str(self, mode: str) -> str:
        inner = "".join(str(p) for p in self._parts)
        if mode == "html":
            return f"<code>{_escape_for_mode(inner, 'html')}</code>"
        return f"`{inner}`"


class Pre(_Node):
    """Code block with optional language.

    ::

        Pre("x = 42\\nprint(x)", language="python")
    """

    def __init__(self, *parts: str | _Node, language: str = "") -> None:
        super().__init__(*parts)
        self._language = language

    def _to_str(self, mode: str) -> str:
        inner = "".join(str(p) for p in self._parts)
        if mode == "html":
            escaped = _escape_for_mode(inner, "html")
            if self._language:
                return f'<pre><code class="{self._language}">{escaped}</code></pre>'
            return f"<pre>{escaped}</pre>"
        return f"```{self._language}\n{inner}\n```"


class Link(_Node):
    """Hyperlink: ``<a href="url">text</a>`` / ``[text](url)``.

    ::

        Link("Click here", url="https://example.com")
        Link(Bold("Important"), url="https://example.com")
    """

    def __init__(self, text: str | _Node, url: str) -> None:
        super().__init__(text)
        self._url = url

    def _to_str(self, mode: str) -> str:
        inner = self._render_children(mode)
        if mode == "html":
            return f'<a href="{self._url}">{inner}</a>'
        return f"[{inner}]({self._url})"


class Mention(_Node):
    """VK Teams user mention: ``@[user_id]``.

    ::

        Mention("user@company.ru")
    """

    def __init__(self, user_id: str) -> None:
        super().__init__()
        self._user_id = user_id

    def _to_str(self, mode: str) -> str:
        if mode == "html":
            return f"@[{self._user_id}]"
        return f"@\\[{_Markdown.escape(self._user_id)}\\]"


class Quote(_Node):
    """Block quote: ``<blockquote>...</blockquote>`` / ``>...``."""

    def _to_str(self, mode: str) -> str:
        inner = self._render_children(mode)
        if mode == "html":
            return f"<blockquote>{inner}</blockquote>"
        lines = inner.split("\n")
        return "\n".join(f">{line}" for line in lines)


class Raw(_Node):
    """Pre-rendered content — passed through **without** escaping.

    Use when you have already-formatted text::

        Raw(html.bold("Hello"))   # not escaped again

    .. warning::
        ``Raw`` bypasses escaping for *both* modes.  Only use when you
        control the target parse mode.
    """

    def _to_str(self, mode: str) -> str:
        return "".join(str(p) for p in self._parts)


# ── Singleton instances ──────────────────────────────────────

md = _Markdown()
html = _HTML()


# ── split_text ───────────────────────────────────────────────


def split_text(text: str, max_length: int = 4096) -> list[str]:
    """Split text into chunks of at most *max_length* characters.

    Tries to split on newlines first, then on spaces, then hard-cuts.

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
