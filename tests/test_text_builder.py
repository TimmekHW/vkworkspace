"""Tests for ``vkworkspace.utils.text`` — MarkdownV2 / HTML rendering.

Pins the VK Teams rules: inline code is a single backtick, and every special
character that is not a style marker must be backslash-escaped — inside code /
pre too (unescaped ``_`` ``-`` ``(`` inside code → «Format error»; a lone ``\\``
inside code is consumed as an escape character).
"""

from __future__ import annotations

import pytest

from vkworkspace.utils.text import Bold, Code, Italic, Pre, Text, html, md

BT = "`"


# ── string helpers ──────────────────────────────────────────────────────


def test_md_escape_specials():
    assert md.escape("a_b*c[d]e(f)g~h`i>j#k+l-m=n|o{p}q.r!s\\t") == (
        "a\\_b\\*c\\[d\\]e\\(f\\)g\\~h\\`i\\>j\\#k\\+l\\-m\\=n\\|o\\{p\\}q\\.r\\!s\\\\t"
    )


def test_md_code_escapes_inner_specials():
    assert md.code("nginx") == "`nginx`"
    assert md.code("x = 1") == "`x \\= 1`"
    assert md.code("a_b.c-d (x)") == "`a\\_b\\.c\\-d \\(x\\)`"
    assert md.code(f"a{BT}b") == "`a\\`b`"
    assert md.code("C:\\dir") == "`C:\\\\dir`"


def test_md_pre_escapes_inner():
    assert md.pre(f"a{BT}b") == "```\na\\`b\n```"
    assert md.pre("print(1)", "python") == "```python\nprint\\(1\\)\n```"


def test_html_code_helper_wraps_only():
    """String helpers wrap; the caller escapes with ``html.escape`` (html.escape is the
    right escaping inside <code>, unlike md.escape inside backticks)."""
    assert html.code("x") == "<code>x</code>"
    assert html.code(html.escape("x < 1 & y")) == "<code>x &lt; 1 &amp; y</code>"


# ── Code / Pre nodes ────────────────────────────────────────────────────


def test_code_node_md_escapes_inner():
    assert Code(f"a{BT}b").as_markdown() == "`a\\`b`"
    assert Code("C:\\dir").as_markdown() == "`C:\\\\dir`"
    assert Code("get_user()").as_markdown() == "`get\\_user\\(\\)`"
    assert Code("nginx.conf").as_markdown() == "`nginx\\.conf`"


def test_code_node_html_escapes_entities():
    assert Code("x < 1").as_html() == "<code>x &lt; 1</code>"


def test_code_node_is_monospace_in_both_modes():
    assert Code("x").as_markdown() == "`x`"
    assert Code("x").as_html() == "<code>x</code>"


def test_code_with_nested_node_renders_plain_text():
    # code cannot contain other styles — nested nodes contribute text only
    assert Code(Bold("x")).as_markdown() == "`x`"
    assert Code(Bold("x")).as_html() == "<code>x</code>"
    assert Code("a ", Italic("b")).as_markdown() == "`a b`"


def test_pre_node_md_escapes_inner_and_keeps_language():
    assert Pre(f"a{BT}b", language="py").as_markdown() == "```py\na\\`b\n```"
    assert Pre("x").as_markdown() == "```\nx\n```"
    assert Pre("x = 42\nprint(x)", language="python").as_markdown() == (
        "```python\nx \\= 42\nprint\\(x\\)\n```"
    )


def test_pre_node_html():
    assert Pre("x < 1", language="python").as_html() == (
        '<pre><code class="python">x &lt; 1</code></pre>'
    )
    assert Pre("x").as_html() == "<pre>x</pre>"


# ── typed backticks are literal text ────────────────────────────────────


def test_typed_backticks_in_text_are_literal_md():
    out = Text(f"use {BT}x{BT} here").as_markdown()
    assert out == "use \\`x\\` here"  # escaped → rendered as literal backticks


def test_typed_backticks_in_text_are_literal_html():
    assert Text(f"use {BT}x{BT} here").as_html() == f"use {BT}x{BT} here"


def test_monospace_requires_code_node():
    node = Text("use ", Code("x"), " here ", Bold("b"))
    assert node.as_markdown() == "use `x` here *b*"
    assert node.as_html() == "use <code>x</code> here <b>b</b>"


def test_helper_inside_builder_double_escapes():
    """Documented footgun: md.* strings get escaped again by the builder."""
    assert Text(md.code("x")).as_markdown() == "\\`x\\`"
    assert Text(md.bold("x")).as_markdown() == "\\*x\\*"


# ── as_kwargs / str ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("HTML", {"text": "<b>x</b>", "parse_mode": "HTML"}),
        ("MarkdownV2", {"text": "*x*", "parse_mode": "MarkdownV2"}),
        ("md", {"text": "*x*", "parse_mode": "MarkdownV2"}),
    ],
)
def test_as_kwargs_modes(mode: str, expected: dict[str, str]):
    assert Bold("x").as_kwargs(mode) == expected


def test_str_renders_html():
    assert str(Code("x")) == "<code>x</code>"
    assert f"{Bold('x')}" == "<b>x</b>"
