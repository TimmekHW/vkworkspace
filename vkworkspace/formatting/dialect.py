"""VK Teams formatting dialects — what one server version accepts.

A dialect is a TOML file: which styles the server renders in MarkdownV2 and
HTML, how text is escaped, the markup templates, and the plain-text fallbacks
used where a style is not supported. Built-in dialects live in
``vkworkspace/formatting/dialects/``; a path to any ``.toml`` file works as
well, and a file can ``extends`` another dialect and list only what differs.

::

    from vkworkspace.formatting import get_dialect

    dialect = get_dialect("vkteams-25.4")
    dialect.status("italic", "markdownv2")      # "untested"
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, Mapping
from functools import lru_cache
from importlib import resources
from pathlib import Path
from string import Formatter
from typing import Any, TypeAlias

STYLES: tuple[str, ...] = (
    "bold",
    "italic",
    "underline",
    "strikethrough",
    "inline_code",
    "pre",
    "link",
    "mention",
    "quote",
    "ordered_list",
    "unordered_list",
)
MODES: tuple[str, ...] = ("markdownv2", "html")
STATUSES: tuple[str, ...] = ("yes", "no", "untested")

DEFAULT_DIALECT = "vkteams-25.4"
"""Dialect of :func:`~vkworkspace.formatting.from_markdown` when none is given."""

DOCS_DIALECT = "vkteams-docs"
"""Dialect of hand-built nodes (``Bold``, ``Code``, …) when none is given."""

DIALECT_ENV = "VKT_DIALECT"
"""Environment variable that overrides both defaults (a dialect name or a path)."""

_PACKAGE = "vkworkspace.formatting"
_TOP_KEYS = frozenset(
    {
        "name",
        "description",
        "support",
        "exclusive",
        "markdownv2",
        "html",
        "fallback",
        "highlight",
        "limits",
    }
)
_HIGHLIGHTS = ("", "bold", "italic", "underline", "strikethrough")
_MODE_KEYS = frozenset(
    {"escape", "code_escape", "url_escape", "language_pattern", "list_separator", "markup"}
)
_ESCAPE_KEYS = {"text": "escape", "code": "code_escape", "url": "url_escape"}

# template key -> fields it may use
_MARKUP_FIELDS: dict[str, frozenset[str]] = {
    "bold": frozenset({"text", "line"}),
    "italic": frozenset({"text", "line"}),
    "underline": frozenset({"text", "line"}),
    "strikethrough": frozenset({"text", "line"}),
    "inline_code": frozenset({"text"}),
    "pre": frozenset({"text"}),
    "pre_language": frozenset({"text", "language"}),
    "link": frozenset({"text", "url"}),
    "mention": frozenset({"id"}),
    "quote": frozenset({"text", "line"}),
    "ordered_list": frozenset({"items"}),
    "unordered_list": frozenset({"items"}),
    "ordered_item": frozenset({"n", "text"}),
    "unordered_item": frozenset({"text"}),
}
_FALLBACK_FIELDS: dict[str, frozenset[str]] = {
    "bold": frozenset({"text", "line"}),
    "italic": frozenset({"text", "line"}),
    "underline": frozenset({"text", "line"}),
    "strikethrough": frozenset({"text", "line"}),
    "inline_code": frozenset({"text"}),
    "link": frozenset({"text", "url"}),
    "mention": frozenset({"id"}),
    "quote": frozenset({"text", "line"}),
    "ordered_item": frozenset({"n", "text"}),
    "unordered_item": frozenset({"text"}),
}
# a style rendered with markup needs these templates
_REQUIRED_MARKUP: dict[str, tuple[str, ...]] = {
    "ordered_list": ("ordered_list", "ordered_item"),
    "unordered_list": ("unordered_list", "unordered_item"),
}

_HTML_ENTITIES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


class DialectError(ValueError):
    """A dialect is unknown, or its file is malformed."""


def _identity(text: str) -> str:
    return text


def _escaper(mode: str, chars: str) -> Callable[[str], str]:
    """Escape function for *chars*: backslash in MarkdownV2, entities in HTML."""
    if not chars:
        return _identity
    if mode == "html":
        table = str.maketrans({c: _HTML_ENTITIES.get(c, f"&#{ord(c)};") for c in chars})
        return lambda text: text.translate(table)
    pattern = re.compile(f"[{re.escape(chars)}]")
    return lambda text: pattern.sub(r"\\\g<0>", text)


class _Template:
    """A ``{field}`` template; ``{line}`` repeats the template for every line of ``text``."""

    __slots__ = ("_parts", "fields", "per_line")

    def __init__(self, source: str, where: str, allowed: frozenset[str]) -> None:
        try:
            parsed = list(Formatter().parse(source))
        except ValueError as exc:
            raise DialectError(f"{where}: {exc}") from None
        self._parts: list[tuple[str, str | None]] = []
        for literal, field, spec, conversion in parsed:
            if field is not None and (spec or conversion or field not in allowed):
                fields = ", ".join(f"{{{name}}}" for name in sorted(allowed))
                raise DialectError(f"{where}: unexpected {{{field}}} — allowed: {fields}")
            self._parts.append((literal, field))
        self.fields = frozenset(field for _, field in self._parts if field is not None)
        self.per_line = "line" in self.fields

    def fill(self, values: Mapping[str, str], literal: Callable[[str], str] = _identity) -> str:
        if self.per_line:
            lines = values.get("text", "").split("\n")
            return "\n".join(self._fill({**values, "line": line}, literal) for line in lines)
        return self._fill(values, literal)

    def _fill(self, values: Mapping[str, str], literal: Callable[[str], str]) -> str:
        out: list[str] = []
        for text, field in self._parts:
            if text:
                out.append(literal(text))
            if field is not None:
                out.append(values[field])
        return "".join(out)


class _ModeRules:
    __slots__ = ("escapers", "language_pattern", "list_separator", "markup")

    def __init__(self, mode: str, data: Mapping[str, Any], source: str) -> None:
        unknown = set(data) - _MODE_KEYS
        if unknown:
            raise DialectError(f"{source}: unknown keys in [{mode}]: {', '.join(sorted(unknown))}")
        self.escapers = {
            where: _escaper(mode, _string(data, key, f"{source} [{mode}]"))
            for where, key in _ESCAPE_KEYS.items()
        }
        pattern = _string(data, "language_pattern", f"{source} [{mode}]")
        try:
            self.language_pattern = re.compile(pattern) if pattern else None
        except re.error as exc:
            raise DialectError(f"{source} [{mode}] language_pattern: {exc}") from None
        self.list_separator = _string(data, "list_separator", f"{source} [{mode}]")
        self.markup = _templates(
            _table(data, "markup", f"{source} [{mode}]"),
            _MARKUP_FIELDS,
            f"{source} [{mode}.markup]",
        )


def _string(data: Mapping[str, Any], key: str, where: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise DialectError(f"{where} {key}: expected a string")
    return value


def _table(data: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise DialectError(f"{where}: [{key}] must be a table")
    return value


def _templates(
    table: Mapping[str, Any], fields: Mapping[str, frozenset[str]], where: str
) -> dict[str, _Template]:
    templates: dict[str, _Template] = {}
    for key, template in table.items():
        if key not in fields or not isinstance(template, str):
            raise DialectError(f"{where}: bad entry {key!r}")
        templates[key] = _Template(template, f"{where} {key}", fields[key])
    return templates


def _parse_support(table: Mapping[str, Any], source: str) -> dict[str, dict[str, str]]:
    support: dict[str, dict[str, str]] = {}
    for style, modes in table.items():
        if style not in STYLES or not isinstance(modes, dict):
            raise DialectError(f"{source}: bad [support] entry {style!r}")
        for mode, status in modes.items():
            if mode not in MODES or status not in STATUSES:
                raise DialectError(
                    f"{source}: [support] {style}.{mode} = {status!r} — "
                    f"modes {MODES}, statuses {STATUSES}"
                )
        support[style] = dict(modes)
    return support


def _parse_exclusive(table: Mapping[str, Any], source: str) -> dict[str, frozenset[str]]:
    """Pairs of styles that cannot be nested, in both directions."""
    exclusive: dict[str, set[str]] = {style: set() for style in STYLES}
    for style, others in table.items():
        if style not in STYLES or not isinstance(others, list) or set(others) - set(STYLES):
            raise DialectError(f"{source}: bad [exclusive] entry {style!r}")
        for other in others:
            exclusive[style].add(other)
            exclusive[other].add(style)
    return {style: frozenset(others) for style, others in exclusive.items()}


def _parse_highlight(table: Mapping[str, Any], source: str) -> str:
    """Style that wraps inline code (``""`` — none)."""
    unknown = set(table) - {"inline_code"}
    if unknown:
        raise DialectError(f"{source}: unknown keys in [highlight]: {', '.join(sorted(unknown))}")
    style = table.get("inline_code", "")
    if style not in _HIGHLIGHTS:
        raise DialectError(f"{source}: [highlight] inline_code = {style!r} — one of {_HIGHLIGHTS}")
    return style


class Dialect:
    """Formatting rules of one VK Teams server version (see :func:`get_dialect`)."""

    def __init__(self, data: Mapping[str, Any], source: str) -> None:
        unknown = set(data) - _TOP_KEYS
        if unknown:
            raise DialectError(f"{source}: unknown keys: {', '.join(sorted(unknown))}")
        self.name: str = str(data.get("name", source))
        self.description: str = str(data.get("description", ""))
        self.source = source
        self._support = _parse_support(_table(data, "support", source), source)
        self._exclusive = _parse_exclusive(_table(data, "exclusive", source), source)
        self._modes = {mode: _ModeRules(mode, _table(data, mode, source), source) for mode in MODES}
        self._fallback = _templates(
            _table(data, "fallback", source), _FALLBACK_FIELDS, f"{source} [fallback]"
        )
        missing = set(_FALLBACK_FIELDS) - set(self._fallback)
        if missing:
            raise DialectError(f"{source}: [fallback] misses {', '.join(sorted(missing))}")
        for style in STYLES:
            for mode in MODES:
                for key in _REQUIRED_MARKUP.get(style, (style,)):
                    if self.status(style, mode) == "yes" and key not in self._modes[mode].markup:
                        raise DialectError(
                            f"{source}: {style} is supported in {mode} but [{mode}.markup] "
                            f"has no {key!r}"
                        )
        max_length = _table(data, "limits", source).get("max_length", 4096)
        if not isinstance(max_length, int) or max_length < 1:
            raise DialectError(f"{source}: [limits] max_length must be a positive integer")
        self.max_length: int = max_length
        self.code_highlight: str = _parse_highlight(_table(data, "highlight", source), source)

    def __repr__(self) -> str:
        return f"Dialect({self.name!r})"

    def status(self, style: str, mode: str) -> str:
        """``"yes"`` / ``"no"`` / ``"untested"`` for *style* in *mode*."""
        return self._support.get(style, {}).get(mode, "no")

    def native(self, style: str, mode: str, inside: frozenset[str] = frozenset()) -> bool:
        """Whether *style* is rendered with markup in *mode* when nested in the *inside* styles."""
        return (
            mode in self._modes
            and self.status(style, mode) == "yes"
            and not self._exclusive[style] & inside
        )

    def escape(self, text: str, mode: str, where: str = "text") -> str:
        """Escape *text* for *mode*; *where* is ``"text"``, ``"code"`` or ``"url"``."""
        rules = self._modes.get(mode)
        return rules.escapers[where](text) if rules else text

    def has_markup(self, key: str, mode: str, field: str | None = None) -> bool:
        """Whether *mode* has the *key* template (and it uses ``{field}``, if given)."""
        rules = self._modes.get(mode)
        template = rules.markup.get(key) if rules else None
        return template is not None and (field is None or field in template.fields)

    def markup(self, key: str, mode: str, **values: str) -> str:
        """Fill the *key* markup template of *mode*; *values* are already escaped."""
        return self._modes[mode].markup[key].fill(values)

    def fallback(self, key: str, mode: str, **values: str) -> str:
        """Fill the *key* fallback template; its literal text is escaped for *mode*."""
        return self._fallback[key].fill(values, lambda text: self.escape(text, mode))

    def language(self, language: str, mode: str) -> str:
        """*language* of a code block if the server accepts it in *mode*, else ``""``."""
        rules = self._modes.get(mode)
        if not language or rules is None or rules.language_pattern is None:
            return language
        return language if rules.language_pattern.fullmatch(language) else ""

    def list_separator(self, mode: str) -> str:
        """Text between list items in *mode*."""
        return self._modes[mode].list_separator


DialectLike: TypeAlias = "str | Path | Dialect"


def available_dialects() -> list[str]:
    """Names of the built-in dialects."""
    folder = resources.files(_PACKAGE) / "dialects"
    return sorted(item.name[:-5] for item in folder.iterdir() if item.name.endswith(".toml"))


def get_dialect(dialect: DialectLike | None = None) -> Dialect:
    """Load a dialect by built-in name or ``.toml`` path.

    ``None`` → the ``VKT_DIALECT`` environment variable → :data:`DEFAULT_DIALECT`.
    Loaded dialects are cached.
    """
    if isinstance(dialect, Dialect):
        return dialect
    if dialect is None:
        dialect = os.environ.get(DIALECT_ENV) or DEFAULT_DIALECT
    return _load(str(dialect))


@lru_cache(maxsize=32)
def _load(spec: str) -> Dialect:
    data, source = _read(spec, None, ())
    return Dialect(data, source)


def _is_path(spec: str) -> bool:
    return spec.endswith(".toml") or "/" in spec or "\\" in spec


def _read(spec: str, base: Path | None, chain: tuple[str, ...]) -> tuple[dict[str, Any], str]:
    """TOML data of *spec* with its ``extends`` chain merged in, and where it came from."""
    if _is_path(spec):
        path = Path(spec)
        if base is not None and not path.is_absolute():
            path = base / path
        source = str(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DialectError(f"cannot read dialect file {source}: {exc}") from None
    else:
        file = resources.files(_PACKAGE) / "dialects" / f"{spec}.toml"
        if not file.is_file():
            known = ", ".join(available_dialects())
            raise DialectError(f"unknown dialect {spec!r}; built-in: {known} (or a .toml path)")
        source = spec
        text = file.read_text(encoding="utf-8")
    if source in chain:
        raise DialectError(f"dialect cycle: {' -> '.join((*chain, source))}")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DialectError(f"{source}: {exc}") from None
    data.setdefault("name", Path(source).stem if _is_path(spec) else spec)
    data.setdefault("description", "")
    parent = data.pop("extends", None)
    if parent is None:
        return data, source
    if not isinstance(parent, str):
        raise DialectError(f"{source}: extends must be a dialect name or path")
    parent_base = Path(source).parent if _is_path(source) else None
    parent_data, _ = _read(parent, parent_base, (*chain, source))
    return _merge(parent_data, data), source


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Tables merged key by key; other values of *override* win."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged
