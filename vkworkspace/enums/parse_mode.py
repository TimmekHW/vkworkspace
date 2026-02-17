from enum import StrEnum


class ParseMode(StrEnum):
    """Message text formatting mode.

    Use with ``bot.send_text(parse_mode=...)`` or ``Bot(parse_mode=...)``
    to set a global default.
    """

    MARKDOWNV2 = "MarkdownV2"
    HTML = "HTML"
