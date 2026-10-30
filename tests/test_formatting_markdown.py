"""Golden tests for ``from_markdown`` — GFM in, what VK Teams receives out.

Default dialect ``vkteams-25.4``: every style was checked live on 30.10.2026;
inline code is wrapped in bold (``[highlight]``). The MarkdownV2 expectations
for code mirror the live checks — every special character escaped inside code
too. ``tests/data/untested.toml`` keeps only bold, code and mentions, for the
fallbacks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vkworkspace.formatting import DIALECT_ENV, from_markdown
from vkworkspace.utils.text import Text, md

UNTESTED = str(Path(__file__).parent / "data" / "untested.toml")


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DIALECT_ENV, raising=False)


def _md(text: str) -> str:
    return from_markdown(text).as_markdown()


def _html(text: str) -> str:
    return from_markdown(text).as_html()


# ── code stays monospace, everything inside escaped ─────────────────────


def test_inline_code():
    assert _md("смотри `nginx`") == "смотри *`nginx`*"


def test_inline_code_inner_specials_escaped():
    assert _md("`a_b.c-d (x)`") == "*`a\\_b\\.c\\-d \\(x\\)`*"
    assert _md("смотри `nginx.conf`") == "смотри *`nginx\\.conf`*"


def test_inline_code_backslash_escaped():
    assert _md("путь `C:\\logs\\app.log`") == "путь *`C:\\\\logs\\\\app\\.log`*"


def test_fenced_block():
    src = "лог:\n```bash\ntail -n 50 app.log | grep -i error\n```\nконец."
    assert _md(src) == "лог:\n```bash\ntail \\-n 50 app\\.log \\| grep \\-i error\n```\nконец\\."


def test_fenced_block_without_language():
    assert _md("```\nx = 1\n```") == "```\nx \\= 1\n```"


def test_fenced_block_language():
    assert _md("```c++\nx\n```") == "```c++\nx\n```"  # D15
    assert _md("```c#\nx\n```") == "```\nx\n```"  # not checked: dropped
    assert from_markdown("```c#\nx\n```", dialect="vkteams-docs").as_markdown() == ("```c#\nx\n```")


def test_indented_code_block():
    assert _md("    x = 1") == "```\nx \\= 1\n```"


def test_one_line_triple_backticks_become_inline_code():
    assert _md("запусти ```kubectl get pods```") == "запусти *`kubectl get pods`*"


def test_several_inline_spans():
    assert _md("`a` и `b`.") == "*`a`* и *`b`*\\."


def test_markup_inside_code_is_literal():
    assert _md("`**kwargs`") == "*`\\*\\*kwargs`*"
    assert _md("`@[x]`") == "*`@\\[x\\]`*"


def test_unpaired_backtick_is_literal():
    assert _md("it`s") == "it\\`s"


def test_escaped_backticks_are_literal():
    assert _md("a \\`b\\` c") == "a \\`b\\` c"


def test_nul_dropped():
    assert _md("a\x00 `x`") == "a *`x`*"


# ── inline code highlighted with bold ───────────────────────────────────


def test_inline_code_not_bolded_twice_inside_bold():
    assert _md("**смотри `x`**") == "*смотри `x`*"
    assert _html("**смотри `x`**") == "<b>смотри <code>x</code></b>"


def test_inline_code_highlight_comes_from_the_dialect():
    assert from_markdown("`x`", dialect="vkteams-docs").as_markdown() == "`x`"
    assert from_markdown("`x`").as_plain() == "x"


# ── bold ────────────────────────────────────────────────────────────────


def test_bold():
    assert _md("**Статус:** работает") == "*Статус:* работает"
    assert _html("**Статус:** работает") == "<b>Статус:</b> работает"


def test_bold_around_inline_code():
    assert _md("**смотри `x`**") == "*смотри `x`*"


def test_heading_becomes_bold():
    assert _md("## Итог\nтекст") == "*Итог*\nтекст"


def test_heading_with_bold_does_not_nest_bold():
    """A heading containing **bold** must not emit <b><b> — the server rejects it."""
    assert _html("### Шаг **3** готов") == "<b>Шаг 3 готов</b>"
    assert _md("### Шаг **3** готов") == "*Шаг 3 готов*"
    assert _html("## **`код`** в заголовке") == "<b><code>код</code> в заголовке</b>"


# ── plain text is escaped as before ─────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "версия 1.2 (бета) — https://example.com/a_b?x=1&y=2",
        "почта ivanov.ii@example.com, ссылка AoGmiBT40Is_7FSiPA",
        "символы ~ > # + - = | { } . ! snake_case",
    ],
)
def test_text_without_markup_fully_escaped(text: str):
    assert _md(text) == md.escape(text)


def test_raw_html_stays_text():
    assert _md("<b>x</b>") == "<b\\>x</b\\>"
    assert _html("<b>x</b> & <br>") == "&lt;b&gt;x&lt;/b&gt; &amp; &lt;br&gt;"


def test_paragraph_spacing_follows_source():
    assert _md("a\nb") == "a\nb"
    assert _md("a\n\nb") == "a\n\nb"
    assert _md("a\n\n\n\nb") == "a\n\nb"
    assert _md("a\r\n\r\nb") == "a\n\nb"


# ── mentions ────────────────────────────────────────────────────────────


def test_mention_survives_every_mode():
    doc = from_markdown("Инициатор: @[ivanov@corp.ru] и @[1000002570]")
    assert doc.as_markdown() == "Инициатор: @\\[ivanov@corp\\.ru\\] и @\\[1000002570\\]"
    assert doc.as_html() == "Инициатор: @[ivanov@corp.ru] и @[1000002570]"
    assert doc.as_plain() == "Инициатор: @[ivanov@corp.ru] и @[1000002570]"


def test_mention_is_never_a_reference_link():
    assert _md("[id]: http://x\n\n@[id] и [id]") == "@\\[id\\] и [id](http://x)"


def test_mention_in_bold():
    assert _md("**@[a@b.c]**") == "*@\\[a@b\\.c\\]*"


# ── styles ──────────────────────────────────────────────────────────────


def test_styles():
    src = "*курсив* ~~старое~~ [дашборд](https://grafana.example/d/1_(a))"
    assert _md(src) == "_курсив_ ~старое~ [дашборд](https://grafana.example/d/1_(a\\))"
    assert _html(src) == (
        '<i>курсив</i> <s>старое</s> <a href="https://grafana.example/d/1_(a)">дашборд</a>'
    )


def test_unchecked_styles_fall_back():
    doc = from_markdown("*курсив* ~~старое~~ [дашборд](https://grafana.example/d/1)", UNTESTED)
    assert doc.as_markdown() == "курсив \\~старое\\~ дашборд \\(https://grafana\\.example/d/1\\)"
    assert doc.as_html() == "курсив ~старое~ дашборд (https://grafana.example/d/1)"


def test_docs_dialect_renders_them():
    doc = from_markdown(
        "*курсив* ~~старое~~ [дашборд](https://grafana.example/d/1)", dialect="vkteams-docs"
    )
    assert doc.as_markdown() == "_курсив_ ~старое~ [дашборд](https://grafana.example/d/1)"
    assert doc.as_html() == (
        '<i>курсив</i> <s>старое</s> <a href="https://grafana.example/d/1">дашборд</a>'
    )


def test_render_time_dialect_overrides_binding():
    doc = from_markdown("*x*", dialect=UNTESTED)
    assert doc.as_markdown() == "x"
    assert doc.as_markdown(dialect="vkteams-docs") == "_x_"


def test_env_dialect(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DIALECT_ENV, UNTESTED)
    assert _md("*x*") == "x"


def test_autolink_is_plain_text():
    """A link showing its own URL goes as text: clients linkify it, nothing to escape."""
    assert _md("<https://a.example/x_(y)>") == "https://a\\.example/x\\_\\(y\\)"
    assert _md("<ivanov@corp.ru>") == "ivanov@corp\\.ru"
    assert _html("[https://a.example](https://a.example)") == "https://a.example"


def test_image_becomes_link():
    assert _html("![схема](http://img.example/a.png)") == (
        '<a href="http://img.example/a.png">схема</a>'
    )
    assert _html("![](http://img.example/a.png)") == "http://img.example/a.png"
    assert from_markdown("![схема](http://i.example/a.png)", UNTESTED).as_html() == (
        "схема (http://i.example/a.png)"
    )


def test_lists():
    src = "- раз\n- два\n\n1. один\n2. два"
    assert _md(src) == "- раз\n- два\n\n1. один\n2. два"
    assert _html(src) == "<ul><li>раз</li><li>два</li></ul>\n\n<ol><li>один</li><li>два</li></ol>"


def test_lists_with_nested_or_multiline_items_or_start_are_text():
    """List markup was seen for one-line items numbered from 1 only."""
    src = "- раз\n- два\n  - вложенный\n\n3. три\n4. четыре"
    assert _md(src) == "• раз\n• два\n  • вложенный\n\n3\\. три\n4\\. четыре"
    assert _html(src) == "• раз\n• два\n  • вложенный\n\n3. три\n4. четыре"
    assert _html("1. первый\n   продолжение\n2. второй") == "1. первый\n   продолжение\n2. второй"


def test_quote():
    assert _html("> цитата `x`") == "<blockquote>цитата <b><code>x</code></b></blockquote>"
    assert _md("> цитата `x`\n> вторая") == ">цитата *`x`*\n>вторая"
    assert from_markdown("> цитата", dialect=UNTESTED).as_markdown() == "│ цитата"


def test_code_block_inside_quote_becomes_inline_code_lines():
    """<pre> inside <blockquote> is a «Format error» — each line becomes inline code."""
    src = "> Alert:\n>\n> ```\n> ERROR db_pool-1 (timeout)\n>\n> retry\n> ```"
    assert _html(src) == (
        "<blockquote>Alert:\n\n<code>ERROR db_pool-1 (timeout)</code>\n\n"
        "<code>retry</code></blockquote>"
    )
    assert _md(src) == ">Alert:\n>\n>`ERROR db\\_pool\\-1 \\(timeout\\)`\n>\n>`retry`"


def test_table_becomes_monospace_block():
    src = "| Сервис | Статус |\n|:-|-:|\n| api | `ok` |\n| db | **down** |"
    table = "Сервис │ Статус\n───────┼───────\napi    │     ok\ndb     │   down"
    assert from_markdown(src).as_plain() == table
    assert _html(src) == f"<pre>{table}</pre>"


def test_horizontal_rule():
    assert _md("a\n\n---\n\nb") == "a\n\n———\n\nb"


# ── the incident bot's summary, end to end ──────────────────────────────

SUMMARY = (
    "**Итог:** сервис `payment-api` упал, см. `nginx.conf` и лог:\n"
    "```bash\ntail -n 50 /var/log/app.log | grep -i error\n```\n"
    "Причина: `OOMKilled` (exit 137)."
)


def test_summary_markdown():
    assert _md(SUMMARY) == (
        "*Итог:* сервис *`payment\\-api`* упал, см\\. *`nginx\\.conf`* и лог:\n"
        "```bash\ntail \\-n 50 /var/log/app\\.log \\| grep \\-i error\n```\n"
        "Причина: *`OOMKilled`* \\(exit 137\\)\\."
    )


def test_summary_html():
    assert _html(SUMMARY) == (
        "<b>Итог:</b> сервис <b><code>payment-api</code></b> упал, "
        "см. <b><code>nginx.conf</code></b> и лог:\n"
        '<pre><code class="bash">tail -n 50 /var/log/app.log | grep -i error</code></pre>\n'
        "Причина: <b><code>OOMKilled</code></b> (exit 137)."
    )


def test_summary_plain():
    assert from_markdown(SUMMARY).as_plain() == (
        "Итог: сервис payment-api упал, см. nginx.conf и лог:\n"
        "tail -n 50 /var/log/app.log | grep -i error\n"
        "Причина: OOMKilled (exit 137)."
    )


def test_as_kwargs():
    assert from_markdown("**x**").as_kwargs("MarkdownV2") == {
        "text": "*x*",
        "parse_mode": "MarkdownV2",
    }


def test_result_is_a_text_node():
    doc = from_markdown("**x**")
    assert isinstance(doc, Text)
    assert (doc + " y").as_markdown() == "*x* y"
    assert Text("> ", doc).as_markdown() == "\\> *x*"
