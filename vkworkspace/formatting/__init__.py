"""Markdown → VK Teams markup, per server version.

::

    from vkworkspace.formatting import from_markdown

    doc = from_markdown(llm_answer)                    # GFM, the way LLMs write it
    await message.answer(**doc.as_kwargs("MarkdownV2"))

    for part in doc.split("MarkdownV2"):               # long answers
        await message.answer(**part.as_kwargs("MarkdownV2"))

``from_markdown`` returns a :class:`~vkworkspace.utils.text.Text` tree. Its
*dialect* — the formatting rules of one VK Teams server version — decides which
styles become markup and which fall back to plain text, so a message is never
rejected with «Format error» for a style the server does not render.

Dialects are TOML files (``vkworkspace/formatting/dialects/``). A dialect is
picked by name or path: ``from_markdown(text, dialect="vkteams-25.4")`` or
``VKT_DIALECT=/etc/bot/vkteams-26.3.toml``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vkworkspace.formatting.dialect import (
    DEFAULT_DIALECT,
    DIALECT_ENV,
    DOCS_DIALECT,
    Dialect,
    DialectError,
    DialectLike,
    available_dialects,
    get_dialect,
)

if TYPE_CHECKING:
    from vkworkspace.utils.text import Text


def from_markdown(text: str, dialect: DialectLike | None = None) -> Text:
    """Convert Markdown (CommonMark + GFM tables and ``~~strike~~``) to a text tree.

    ``**bold**``, ``*italic*``, ```` `code` ````, fenced blocks, links, lists,
    quotes, headings (→ bold), tables (→ a monospace block) and ``@[user_id]``
    mentions. Raw HTML in the input stays text.

    The tree is bound to *dialect* (``None`` → ``VKT_DIALECT`` →
    :data:`DEFAULT_DIALECT`); render it with ``as_kwargs()``, ``as_markdown()``,
    ``as_html()``, ``as_plain()`` or ``split()``.

    Needs ``markdown-it-py``: ``pip install "vkworkspace[markdown]"``.
    """
    from vkworkspace.formatting.markdown import convert

    return convert(text, dialect)


def from_html(text: str, dialect: DialectLike | None = None) -> Text:
    """Convert HTML — the way bots and LLMs write it for VK Teams — to a text tree.

    ``<b>``, ``<i>``, ``<u>``, ``<s>``, ``<code>``, ``<pre>``, ``<a href>``,
    ``<blockquote>``, ``<ul>`` / ``<ol>``; ``<br>`` → line break; ``<p>``,
    ``<div>``, headings (→ bold) start a new line; a table → a monospace block;
    any other tag keeps its text. Outside ``<code>`` / ``<pre>``, GFM code typed
    in the text (`` `x` ``, ```` ```block``` ````) becomes code and
    ``@[user_id]`` a mention. Entities are decoded; a stray ``<`` stays text.

    The tree is bound to *dialect* like :func:`from_markdown`'s and renders to
    HTML, MarkdownV2 or plain text. Standard library only.
    """
    from vkworkspace.formatting.html_input import convert

    return convert(text, dialect)


__all__ = [
    "DEFAULT_DIALECT",
    "DIALECT_ENV",
    "DOCS_DIALECT",
    "Dialect",
    "DialectError",
    "DialectLike",
    "available_dialects",
    "from_html",
    "from_markdown",
    "get_dialect",
]
