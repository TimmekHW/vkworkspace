"""Golden tests for ``from_html`` — HTML from bots / LLMs in, what VK Teams receives out.

Default dialect ``vkteams-25.4``: every style was checked live on 30.10.2026;
inline code is wrapped in bold (``[highlight]``). ``tests/data/untested.toml``
keeps only bold, code and mentions, for the fallbacks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vkworkspace.formatting import DIALECT_ENV, from_html
from vkworkspace.utils.text import Text

UNTESTED = str(Path(__file__).parent / "data" / "untested.toml")


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DIALECT_ENV, raising=False)


def _html(text: str) -> str:
    return from_html(text).as_html()


# ── GFM code typed into HTML ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("см. `nginx.conf`", "см. <b><code>nginx.conf</code></b>"),
        (
            "<b>Итог</b>: ```kubectl get pods```",
            "<b>Итог</b>: <b><code>kubectl get pods</code></b>",
        ),
        ("лог:\n```\ntail -n 5 `app.log`\n```", "лог:\n<pre>tail -n 5 `app.log`</pre>"),
        ("a<br>b<br/>`c`", "a\nb\n<b><code>c</code></b>"),
        ("<b>Лог</b>:\n```\nx\n```", "<b>Лог</b>:\n<pre>x</pre>"),
        ("<b>см. `x`</b>", "<b>см. <code>x</code></b>"),
        ("```python\nprint(1)\n```", '<pre><code class="python">print(1)</code></pre>'),
        ("```c++\nx\n```", '<pre><code class="c++">x</code></pre>'),
        ("```c#\nx\n```", "<pre>x</pre>"),
    ],
)
def test_code_islands(src: str, expected: str):
    assert _html(src) == expected


@pytest.mark.parametrize("src", ["<b>x</b> &amp; y", "it`s", "без кода"])
def test_text_without_code_unchanged(src: str):
    assert _html(src) == src


def test_code_across_tags_stays_text():
    assert _html("`a <b>b` c</b>") == "`a <b>b` c</b>"


def test_backticks_inside_code_are_literal():
    assert _html("<code>`x`</code>") == "<b><code>`x`</code></b>"


def test_block_inside_bold_becomes_inline_code():
    assert _html("<b>```\nx\n```</b>") == "<b><code>x</code></b>"


def test_email_body_in_quote():
    """<pre> inside <blockquote> is a «Format error» — the block becomes inline code lines."""
    src = (
        "Текст письма:\n\n<blockquote>Alert:\n\n```\nERROR db_pool-1 (timeout)\n```"
        "\n\nsee `nginx.conf`</blockquote>"
    )
    assert _html(src) == (
        "Текст письма:\n\n<blockquote>Alert:\n\n<code>ERROR db_pool-1 (timeout)</code>"
        "\n\nsee <b><code>nginx.conf</code></b></blockquote>"
    )


# ── tags ────────────────────────────────────────────────────────────────


def test_supported_tags_round_trip():
    src = "<b>a</b> <strong>b</strong> <code>x &lt; 1</code>\n<blockquote>q</blockquote>"
    assert _html(src) == (
        "<b>a</b> <b>b</b> <b><code>x &lt; 1</code></b>\n<blockquote>q</blockquote>"
    )


def test_styles():
    src = '<i>курсив</i> <s>старое</s> <a href="https://e.com/?a=1&amp;b=2">ссылка</a>'
    assert _html(src) == (
        '<i>курсив</i> <s>старое</s> <a href="https://e.com/?a=1&b=2">ссылка</a>'
    )  # raw & in href (E5); &amp; there shows "&" in the text (E6)
    assert from_html(src).as_markdown() == "_курсив_ ~старое~ [ссылка](https://e.com/?a=1&b=2)"


def test_unchecked_tags_fall_back():
    src = '<i>курсив</i> <s>старое</s> <a href="https://e.com/a_b">ссылка</a>'
    assert from_html(src, dialect=UNTESTED).as_html() == (
        "курсив ~старое~ ссылка (https://e.com/a_b)"
    )


def test_link_showing_its_url_is_text():
    assert _html('<a href="https://e.com/a">https://e.com/a</a>') == "https://e.com/a"
    assert _html('<a href="https://e.com/a"></a>') == "https://e.com/a"


def test_pre_with_language_class():
    src = '<pre><code class="language-python">print(1 &lt; 2)</code></pre>'
    assert _html(src) == '<pre><code class="python">print(1 &lt; 2)</code></pre>'
    assert from_html(src).as_markdown() == "```python\nprint\\(1 < 2\\)\n```"


def test_pre_drops_newline_after_opening_tag():
    assert _html("<pre>\nx\n</pre>") == "<pre>x</pre>"


def test_paragraphs_divs_and_headings_are_lines():
    src = "<p>Первый</p><p>Второй <b>жирный</b></p><h3>Заголовок</h3>хвост<div>блок</div>"
    assert _html(src) == "Первый\nВторой <b>жирный</b>\n<b>Заголовок</b>\nхвост\nблок"


def test_lists():
    assert _html("<ul>\n<li>раз</li>\n<li>два <b>жирно</b></li>\n</ul>\nпосле") == (
        "<ul><li>раз</li><li>два <b>жирно</b></li></ul>\nпосле"
    )
    assert _html('<ol start="3"><li>три</li><li>четыре</li></ol>') == "3. три\n4. четыре"
    assert _html("<ul><li>раз<br>два</li></ul>") == "• раз\n  два"
    assert from_html("<ul><li>a</li><li>b</li></ul>", dialect=UNTESTED).as_html() == ("• a\n• b")


def test_table_becomes_monospace_block():
    src = (
        "<table><tr><th>Сервис</th><th align='right'>p95</th></tr>"
        "<tr><td>api</td><td>120</td></tr></table>"
    )
    assert from_html(src).as_plain() == "Сервис │ p95\n───────┼────\napi    │ 120"


def test_hr_and_img():
    assert _html('a<hr>b <img src="http://i/x.png" alt="схема"> <img src="http://i/y.png">') == (
        'a\n———\nb <a href="http://i/x.png">схема</a> http://i/y.png'
    )


def test_mentions():
    doc = from_html("Инициатор: @[ivanov@corp.ru], <b>@[1000002570]</b>")
    assert doc.as_html() == "Инициатор: @[ivanov@corp.ru], <b>@[1000002570]</b>"
    assert doc.as_markdown() == "Инициатор: @\\[ivanov@corp\\.ru\\], *@\\[1000002570\\]*"


# ── broken HTML never loses text ────────────────────────────────────────


@pytest.mark.parametrize(
    ("src", "plain"),
    [
        ("x < 1 и y > 2, a<b, List<int>, <5%", "x < 1 и y > 2, a<b, List<int>, <5%"),
        ("<b>незакрытый", "незакрытый"),
        ("</b>лишний закрывающий", "лишний закрывающий"),
        ("<unknown>тег</unknown>", "<unknown>тег</unknown>"),
        ("&amp; &lt; &#x41; &bogus;", "& < A &bogus;"),
        ("<!-- комментарий -->после", "после"),
        ("<script>alert(1)</script>после", "после"),
    ],
)
def test_broken_html(src: str, plain: str):
    assert from_html(src).as_plain() == plain


def test_unclosed_bold_is_closed():
    assert _html("<b>незакрытый") == "<b>незакрытый</b>"


def test_stray_less_than_is_escaped_in_html():
    assert _html("a<b c") == "a&lt;b c"


# ── the rest of the tree API works on HTML input ────────────────────────


def test_plain_fallback_has_no_tags():
    doc = from_html("<b>Сводка</b>: упал `payment-api`\n<blockquote>письмо</blockquote>")
    assert doc.as_plain() == "Сводка: упал payment-api\n│ письмо"


def test_split_never_cuts_a_tag():
    doc = from_html("\n".join(f"<b>Пункт {i}</b>: " + "текст " * 30 for i in range(30)))
    parts = doc.split("HTML", 400)
    assert len(parts) > 1
    for part in parts:
        text = part.as_html()
        assert len(text) <= 400
        assert text.count("<b>") == text.count("</b>")


def test_result_is_a_text_node():
    assert isinstance(from_html("x"), Text)
