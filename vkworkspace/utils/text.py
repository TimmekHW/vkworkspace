"""
Text formatting utilities for VK Teams Bot API.

Three formatting modes are supported:

- **MarkdownV2** — ``parseMode="MarkdownV2"``
- **HTML** — ``parseMode="HTML"``
- **Format ranges** — ``format`` parameter (JSON with offset/length)

Usage::

    from vkworkspace.utils.text import md, html, split_text

    # MarkdownV2
    await message.answer(
        f"{md.bold('Status')}: {md.escape(user_input)}",
        parse_mode="MarkdownV2",
    )

    # HTML
    await message.answer(
        f"{html.bold('Status')}: {html.escape(user_input)}",
        parse_mode="HTML",
    )

    # Split long text
    for chunk in split_text(long_text):
        await message.answer(chunk)
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
