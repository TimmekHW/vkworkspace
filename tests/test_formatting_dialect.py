"""Tests for ``vkworkspace.formatting.dialect`` — loading, ``extends``, validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from vkworkspace.formatting import (
    DEFAULT_DIALECT,
    DIALECT_ENV,
    DOCS_DIALECT,
    Dialect,
    DialectError,
    available_dialects,
    get_dialect,
)
from vkworkspace.formatting.dialect import STYLES, _load


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DIALECT_ENV, raising=False)
    _load.cache_clear()
    yield
    _load.cache_clear()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ── built-in dialects ───────────────────────────────────────────────────


def test_builtin_dialects_listed():
    assert {DEFAULT_DIALECT, DOCS_DIALECT} <= set(available_dialects())


def test_default_dialect():
    assert get_dialect().name == DEFAULT_DIALECT == "vkteams-25.4"


def test_env_overrides_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DIALECT_ENV, DOCS_DIALECT)
    assert get_dialect().name == DOCS_DIALECT


def test_dialect_instance_passes_through():
    dialect = get_dialect(DOCS_DIALECT)
    assert get_dialect(dialect) is dialect
    assert get_dialect(DOCS_DIALECT) is dialect  # cached


def test_docs_dialect_supports_every_style():
    dialect = get_dialect(DOCS_DIALECT)
    for style in STYLES:
        assert dialect.status(style, "markdownv2") == "yes"
        assert dialect.status(style, "html") == "yes"


@pytest.mark.parametrize("style", STYLES)
def test_25_4_renders_every_style(style: str):
    """Live check of 2026-10-30 on a 25.4.3p server."""
    dialect = get_dialect("vkteams-25.4")
    assert dialect.status(style, "markdownv2") == "yes"
    assert dialect.status(style, "html") == "yes"


def test_25_4_url_escaping():
    dialect = get_dialect("vkteams-25.4")
    assert dialect.escape("https://e.com/w/Foo_(bar)", "markdownv2", "url") == (
        "https://e.com/w/Foo_(bar\\)"
    )
    assert dialect.escape("https://e.com/?x=1&y=2", "html", "url") == "https://e.com/?x=1&y=2"


def test_25_4_inherits_docs_markup():
    dialect = get_dialect("vkteams-25.4")
    assert dialect.markup("bold", "markdownv2", text="x") == "*x*"
    assert dialect.markup("mention", "markdownv2", id="a") == "@\\[a\\]"
    assert dialect.description.startswith("VK WorkSpace On-Premise 25.4")


def test_highlight():
    assert get_dialect("vkteams-25.4").code_highlight == "bold"
    assert get_dialect(DOCS_DIALECT).code_highlight == ""


def test_25_4_drops_unchecked_language():
    dialect = get_dialect("vkteams-25.4")
    assert dialect.language("python", "markdownv2") == "python"
    assert dialect.language("c++", "markdownv2") == "c++"
    assert dialect.language("c#", "markdownv2") == ""
    assert dialect.language("objective-c", "html") == ""
    assert get_dialect(DOCS_DIALECT).language("c#", "markdownv2") == "c#"


def test_exclusive_is_symmetric():
    dialect = get_dialect(DOCS_DIALECT)
    assert not dialect.native("pre", "html", frozenset({"quote"}))
    assert not dialect.native("ordered_list", "html", frozenset({"quote"}))
    assert not dialect.native("quote", "html", frozenset({"unordered_list"}))
    assert not dialect.native("mention", "html", frozenset({"link"}))
    assert dialect.native("inline_code", "html", frozenset({"quote", "bold"}))


def test_plain_mode_is_never_native_and_never_escaped():
    dialect = get_dialect(DOCS_DIALECT)
    assert not dialect.native("bold", "plain")
    assert dialect.escape("a_b <c>", "plain") == "a_b <c>"


def test_escape_modes():
    dialect = get_dialect(DOCS_DIALECT)
    assert dialect.escape("a_b.c", "markdownv2") == "a\\_b\\.c"
    assert dialect.escape("x < 1 & y", "html") == "x &lt; 1 &amp; y"
    assert dialect.escape("https://a/b_c", "markdownv2", "url") == "https://a/b_c"


def test_fallback_literals_are_escaped():
    dialect = get_dialect(DOCS_DIALECT)
    assert dialect.fallback("link", "markdownv2", text="t", url="u") == "t \\(u\\)"
    assert dialect.fallback("link", "plain", text="t", url="u") == "t (u)"
    assert dialect.fallback("quote", "plain", text="a\nb") == "│ a\n│ b"


# ── custom files and extends ────────────────────────────────────────────


def test_custom_file_extends_builtin(tmp_path: Path):
    path = _write(
        tmp_path / "vkteams-26.3.toml",
        'extends = "vkteams-25.4"\n[support]\nitalic = { markdownv2 = "no" }\n',
    )
    dialect = get_dialect(path)
    assert dialect.name == "vkteams-26.3"  # not inherited from the parent
    assert dialect.description == ""
    assert dialect.status("italic", "markdownv2") == "no"
    assert dialect.status("italic", "html") == "yes"  # merged key by key
    assert dialect.language("c#", "markdownv2") == ""  # parent's pattern kept
    assert dialect.code_highlight == "bold"


def test_extends_relative_path(tmp_path: Path):
    _write(tmp_path / "base.toml", 'extends = "vkteams-docs"\nname = "base"\n')
    child = _write(
        tmp_path / "child.toml",
        'extends = "base.toml"\n[support]\nbold = { html = "no" }\n',
    )
    dialect = get_dialect(str(child))
    assert dialect.name == "child"
    assert dialect.status("bold", "html") == "no"
    assert dialect.status("bold", "markdownv2") == "yes"


def test_env_accepts_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = _write(tmp_path / "mine.toml", 'extends = "vkteams-docs"\n')
    monkeypatch.setenv(DIALECT_ENV, str(path))
    assert get_dialect().name == "mine"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('extends = "vkteams-docs"\ncolour = 1\n', "unknown keys"),
        ('extends = "vkteams-docs"\n[support]\nbold = { html = "maybe" }\n', "statuses"),
        ('extends = "vkteams-docs"\n[support]\nblink = { html = "yes" }\n', "blink"),
        ('extends = "vkteams-docs"\n[html.markup]\nbold = "<b>{body}</b>"\n', "{body}"),
        ('extends = "vkteams-docs"\n[html.markup]\nbold = "<b>{text</b>"\n', "bold"),
        ('extends = "vkteams-docs"\n[html]\nlanguage_pattern = "["\n', "language_pattern"),
        ('extends = "vkteams-docs"\n[limits]\nmax_length = 0\n', "max_length"),
        ('extends = "vkteams-docs"\n[highlight]\ninline_code = "blink"\n', "highlight"),
        ('extends = "vkteams-docs"\n[highlight]\nlinks = "bold"\n', "highlight"),
        ('extends = "vkteams-docs"\nsupport = "all"\n', "must be a table"),
        ("this is = not toml", "mine.toml"),
    ],
)
def test_malformed_dialect(tmp_path: Path, text: str, message: str):
    path = _write(tmp_path / "mine.toml", text)
    with pytest.raises(DialectError, match=message.replace("{", r"\{").replace("}", r"\}")):
        get_dialect(path)


def test_supported_style_needs_markup(tmp_path: Path):
    text = "[support]\nbold = { html = 'yes' }\n[fallback]\n" + "".join(
        f'{key} = "{{text}}"\n'
        for key in (
            "bold", "italic", "underline", "strikethrough", "inline_code", "quote", "link",
            "ordered_item", "unordered_item",
        )
    )  # fmt: skip
    text += 'mention = "{id}"\n'
    path = _write(tmp_path / "bare.toml", text)
    with pytest.raises(DialectError, match="has no 'bold'"):
        get_dialect(path)


def test_fallback_must_be_complete(tmp_path: Path):
    path = _write(tmp_path / "bare.toml", "[fallback]\nbold = '{text}'\n")
    with pytest.raises(DialectError, match="misses"):
        get_dialect(path)


def test_unknown_dialect_lists_builtins():
    with pytest.raises(DialectError, match="vkteams-docs"):
        get_dialect("vkteams-1999.01")


def test_missing_file():
    with pytest.raises(DialectError, match="cannot read"):
        get_dialect("no/such/dialect.toml")


def test_extends_cycle(tmp_path: Path):
    _write(tmp_path / "a.toml", 'extends = "b.toml"\n')
    path = _write(tmp_path / "b.toml", 'extends = "a.toml"\n')
    with pytest.raises(DialectError, match="cycle"):
        get_dialect(path)


def test_repr():
    assert repr(get_dialect(DOCS_DIALECT)) == "Dialect('vkteams-docs')"
    assert isinstance(get_dialect(DOCS_DIALECT), Dialect)
