from enum import StrEnum


class PartType(StrEnum):
    STICKER = "sticker"
    MENTION = "mention"
    VOICE = "voice"
    FILE = "file"
    FORWARD = "forward"
    REPLY = "reply"
    INLINE_KEYBOARD_MARKUP = "inlineKeyboardMarkup"
