from enum import StrEnum


class StyleType(StrEnum):
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKETHROUGH = "strikethrough"
    LINK = "link"
    MENTION = "mention"
    INLINE_CODE = "inline_code"
    PRE = "pre"
    ORDERED_LIST = "ordered_list"
    UNORDERED_LIST = "unordered_list"
    QUOTE = "quote"
