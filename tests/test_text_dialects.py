"""Text builder nodes rendered through dialects: defaults, fallbacks, as_plain, lists, split."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vkworkspace.formatting import DIALECT_ENV, from_markdown, get_dialect
from vkworkspace.utils.text import (
    Bold,
    Code,
    Italic,
    Link,
    Mention,
    OrderedList,
    Pre,
    Quote,
    Raw,
    Strikethrough,
    Text,
    Underline,
    UnorderedList,
    _width,
)

NEW = "vkteams-25.4"
UNTESTED = str(Path(__file__).parent / "data" / "untested.toml")


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DIALECT_ENV, raising=False)


# ── no dialect: the output of earlier versions ──────────────────────────


@pytest.mark.parametrize(
    ("node", "markdown", "html"),
    [
        (Bold("a.b"), "*a\\.b*", "<b>a.b</b>"),
        (Italic("x"), "_x_", "<i>x</i>"),
        (Underline("x"), "__x__", "<u>x</u>"),
        (Strikethrough("x"), "~x~", "<s>x</s>"),
        (
            Link("t", url="https://a.b/c_d"),
            "[t](https://a.b/c_d)",
            '<a href="https://a.b/c_d">t</a>',
        ),
        (Mention("a@b.c"), "@\\[a@b\\.c\\]", "@[a@b.c]"),
        (Quote("a\nb"), ">a\n>b", "<blockquote>a\nb</blockquote>"),
        (Bold(Italic("x")), "*_x_*", "<b><i>x</i></b>"),
        (Raw("<b>x</b>"), "<b>x</b>", "<b>x</b>"),
    ],
)
def test_default_output_unchanged(node: Text, markdown: str, html: str):
    assert node.as_markdown() == markdown
    assert node.as_html() == html


def test_env_dialect_applies_to_nodes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DIALECT_ENV, UNTESTED)
    assert Italic("x").as_markdown() == "x"


# ── vkteams-25.4 ────────────────────────────────────────────────────────


def test_25_4_link_url_escaping():
    link = Link("t", url="https://e.com/w/Foo_(bar)?a=1&b=2")
    assert link.as_markdown(NEW) == "[t](https://e.com/w/Foo_(bar\\)?a=1&b=2)"
    assert link.as_html(NEW) == '<a href="https://e.com/w/Foo_(bar)?a=1&b=2">t</a>'


def test_same_style_nested_in_itself_is_not_wrapped_twice():
    """Nested <b><b>…</b></b> is a «Format error» in HTML — the inner one is flattened."""
    assert Bold("a ", Bold("b"), " c").as_html("vkteams-docs") == "<b>a b c</b>"
    assert Bold("a ", Bold("b"), " c").as_markdown("vkteams-docs") == "*a b c*"
    assert Italic(Italic("x")).as_html("vkteams-docs") == "<i>x</i>"
    assert Quote("a", Quote("b")).as_html("vkteams-docs") == "<blockquote>ab</blockquote>"
    # a different style still nests
    assert Bold("a ", Italic("b")).as_html("vkteams-docs") == "<b>a <i>b</i></b>"
    # inline code already inside bold is not bold-wrapped again (highlight suppressed)
    assert Bold("x ", Code("y")).as_html(NEW) == "<b>x <code>y</code></b>"
    assert Bold("x ", Code("y")).as_markdown(NEW) == "*x `y`*"


# ── dialect fallbacks ───────────────────────────────────────────────────


def test_unsupported_style_renders_as_text():
    assert Italic("a.b").as_markdown(UNTESTED) == "a\\.b"
    assert Underline("x").as_html(UNTESTED) == "x"
    assert Strikethrough("x").as_markdown(UNTESTED) == "\\~x\\~"
    assert Link("t", url="http://u").as_html(UNTESTED) == "t (http://u)"
    assert Link("http://u", url="http://u").as_html(UNTESTED) == "http://u"


def test_supported_style_inside_fallback_keeps_markup():
    assert Italic("a ", Bold("b")).as_markdown(UNTESTED) == "a *b*"


def test_inline_code_highlight():
    assert Code("x").as_markdown(NEW) == "*`x`*"
    assert Code("x").as_html(NEW) == "<b><code>x</code></b>"
    assert Bold("a ", Code("x")).as_markdown(NEW) == "*a `x`*"  # no bold inside bold
    assert Link(Code("x"), url="u").as_plain(NEW) == "x (u)"
    assert Code("x").as_markdown() == "`x`"  # vkteams-docs: no highlight


def test_highlight_needs_a_rendered_style(tmp_path):
    parent = Path(UNTESTED).as_posix()
    untested = tmp_path / "italic-untested.toml"
    untested.write_text(f'extends = "{parent}"\n[highlight]\ninline_code = "italic"\n', "utf-8")
    assert Code("x").as_markdown(untested) == "`x`"  # italic is untested there
    rendered = tmp_path / "italic-docs.toml"
    rendered.write_text('extends = "vkteams-docs"\n[highlight]\ninline_code = "italic"\n', "utf-8")
    assert Code("x").as_markdown(rendered) == "_`x`_"


def test_text_binding():
    node = Text(Italic("x"), dialect=UNTESTED)
    assert node.as_markdown() == "x"
    assert node.as_markdown(dialect="vkteams-docs") == "_x_"
    assert Text(node).as_markdown() == "x"  # binding below still applies


def test_outermost_binding_wins():
    inner = Text(Italic("x"), dialect="vkteams-docs")
    assert Text(inner, dialect=UNTESTED).as_markdown() == "x"
    assert Text(Text(Italic("x"), dialect=UNTESTED), dialect="vkteams-docs").as_markdown() == (
        "_x_"
    )


def test_binding_accepts_dialect_object():
    assert Text(Italic("x"), dialect=get_dialect(UNTESTED)).as_html() == "x"


def test_add_keeps_binding():
    node = Text(Italic("x"), dialect=UNTESTED)
    assert (node + Italic("y")).as_markdown() == "xy"
    assert ("> " + node).as_markdown() == "\\> x"
    assert (node + Text(Italic("y"))).as_markdown() == "xy"


def test_pre_inside_quote_becomes_inline_code_lines():
    node = Quote("Лог:\n", Pre("a = 1\n\nb_c"))
    assert node.as_html() == "<blockquote>Лог:\n<code>a = 1</code>\n\n<code>b_c</code></blockquote>"
    assert node.as_markdown() == ">Лог:\n>`a \\= 1`\n>\n>`b\\_c`"


def test_pre_inside_bold_falls_back():
    assert Bold(Pre("x")).as_html() == "<b><code>x</code></b>"


def test_mention_inside_link_falls_back_to_text():
    assert Link(Mention("a"), url="http://u").as_plain() == "@[a] (http://u)"


# ── as_plain ────────────────────────────────────────────────────────────


def test_as_plain():
    node = Text(
        Bold("Итог:"), " ", Code("a_b"), " ", Link("дашборд", url="http://g/d"), "\n",
        Quote("цитата\nвторая"), "\n",
        Pre("x < 1", language="python"), "\n",
        Mention("a@b.c"), " ", Raw("<b>raw</b>"),
    )  # fmt: skip
    assert node.as_plain() == (
        "Итог: a_b дашборд (http://g/d)\n│ цитата\n│ вторая\nx < 1\n@[a@b.c] <b>raw</b>"
    )


# ── lists ───────────────────────────────────────────────────────────────


def test_lists_native():
    assert OrderedList("a", Bold("b")).as_html() == "<ol><li>a</li><li><b>b</b></li></ol>"
    assert UnorderedList("a", "b").as_html() == "<ul><li>a</li><li>b</li></ul>"
    assert OrderedList("a.", "b").as_markdown() == "1. a\\.\n2. b"
    assert UnorderedList("a", "b").as_markdown() == "- a\n- b"


def test_lists_fallback():
    assert OrderedList("a", "b", start=9).as_markdown(NEW) == "9\\. a\n10\\. b"
    assert UnorderedList("a\nb", "c").as_plain() == "• a\n  b\n• c"
    assert OrderedList("a\n\nb").as_plain() == "1. a\n\n   b"


def test_list_markup_only_for_one_line_items_from_1():
    """List markup was seen with one-line items numbered from 1 only."""
    assert UnorderedList("a", "b").as_html(NEW) == "<ul><li>a</li><li>b</li></ul>"
    assert UnorderedList("a\nb", "c").as_html(NEW) == "• a\n  b\n• c"
    assert OrderedList("a", start=3).as_html(NEW) == "3. a"
    assert OrderedList("a", start=3).as_markdown(NEW) == "3\\. a"


def test_list_inside_quote_falls_back():
    assert Quote(UnorderedList("a", "b")).as_html() == "<blockquote>• a\n• b</blockquote>"


def test_empty_list():
    assert OrderedList().as_html() == ""
    assert UnorderedList().as_plain() == ""


# ── split ───────────────────────────────────────────────────────────────


def _assert_parts(parts: list[Text], mode: str, limit: int) -> list[str]:
    rendered = [p.as_kwargs(mode)["text"] for p in parts]
    assert all(_width(text) <= limit for text in rendered), [_width(t) for t in rendered]
    return rendered


def _letters(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_split_short_returns_itself():
    node = Text("short")
    assert node.split() == [node]
    assert [p.as_html() for p in Bold("x").split()] == ["<b>x</b>"]


def test_split_between_paragraphs():
    doc = from_markdown("\n\n".join(f"**Пункт {i}.** " + "слово " * 30 for i in range(20)))
    parts = doc.split("MarkdownV2", 500)
    rendered = _assert_parts(parts, "MarkdownV2", 500)
    assert len(parts) > 1
    assert all(text.startswith("*Пункт") for text in rendered)
    assert _letters("".join(p.as_plain() for p in parts)) == _letters(doc.as_plain())


def test_split_code_block_by_lines():
    doc = from_markdown("```python\n" + "\n".join(f"print({i})" for i in range(200)) + "\n```")
    parts = doc.split("MarkdownV2", 300)
    rendered = _assert_parts(parts, "MarkdownV2", 300)
    assert len(parts) > 1
    assert all(t.startswith("```python\n") and t.endswith("\n```") for t in rendered)
    assert _letters("".join(p.as_plain() for p in parts)) == _letters(doc.as_plain())


def test_split_long_line_at_spaces():
    text = " ".join(["слово"] * 400)
    parts = Text(text).split("HTML", 100)
    _assert_parts(parts, "HTML", 100)
    assert all(not p.as_plain().startswith(" ") for p in parts)
    assert " ".join(p.as_plain() for p in parts) == text


def test_split_counts_escaping():
    parts = Text("." * 1000).split("MarkdownV2", 100)
    assert [len(p.as_markdown()) for p in parts] == [100] * 20  # "\." is two characters


def test_split_counts_utf16():
    parts = Text("😀" * 100).split("HTML", 50)
    assert len(parts) == 4  # 2 UTF-16 code units each


def test_split_long_bold_keeps_bold():
    parts = Bold("слово " * 100).split("HTML", 120)
    rendered = _assert_parts(parts, "HTML", 120)
    assert all(t.startswith("<b>") and t.endswith("</b>") for t in rendered)


def test_split_list_continues_numbering():
    node = OrderedList(*(f"пункт {i}" for i in range(1, 31)))
    parts = node.split(None, 100, dialect=NEW)
    rendered = [p.as_plain() for p in parts]
    assert len(parts) > 1
    assert all(len(text) <= 100 for text in rendered)
    second = rendered[1].split("\n")[0]
    number = int(second.split(".")[0])
    assert second == f"{number}. пункт {number}"


def test_split_parts_keep_the_dialect():
    doc = from_markdown("*курсив* " * 200, dialect=UNTESTED)
    parts = doc.split("MarkdownV2", 300)
    assert all("_" not in p.as_markdown() for p in parts)  # still the untested dialect
    parts = Text(Italic("курсив " * 200)).split("MarkdownV2", 300, dialect=UNTESTED)
    assert all("_" not in p.as_markdown() for p in parts)


def test_split_default_limit_from_dialect():
    doc = from_markdown("слово " * 2000)
    parts = doc.split("HTML")
    assert len(parts) == 3
    _assert_parts(parts, "HTML", 4096)


def test_split_long_inline_code():
    parts = Text(Code("a_b." * 100)).split("MarkdownV2", 100)
    rendered = _assert_parts(parts, "MarkdownV2", 100)
    assert all(t.startswith("`") and t.endswith("`") for t in rendered)
    assert "".join(p.as_plain() for p in parts) == "a_b." * 100


def test_split_long_list_item():
    parts = UnorderedList("слово " * 60, "второй").split(None, 80, dialect=NEW)
    rendered = [p.as_plain() for p in parts]
    assert all(len(text) <= 80 for text in rendered)
    assert rendered[0].startswith("• слово")
    assert rendered[-1].endswith("• второй")


def test_split_quote_with_line_prefixes():
    """Each quoted line gets "│ " — the pieces are re-cut until they fit with the prefixes."""
    node = Quote("\n".join(["строка цитаты"] * 40))
    parts = node.split(None, 60)
    rendered = [p.as_plain() for p in parts]
    assert len(parts) > 1
    assert all(len(text) <= 60 for text in rendered)
    assert all(line.startswith("│ ") for text in rendered for line in text.split("\n"))


def test_split_keeps_unsplittable_nodes_whole():
    raw = Raw("<b>" + "x" * 200 + "</b>")
    assert [p.as_html() for p in Text(raw).split("HTML", 50)] == [raw.as_html()]
    mention = Mention("a" * 100)
    assert [p.as_plain() for p in Text(mention).split(None, 20)] == [f"@[{'a' * 100}]"]


def test_repr():
    assert repr(Text("a", Bold("b"))) == "Text('a', Bold('b'))"
    assert repr(Text("a", dialect=NEW)) == "Text('a', dialect='vkteams-25.4')"
    assert repr(Mention("x")) == "Mention('x')"
