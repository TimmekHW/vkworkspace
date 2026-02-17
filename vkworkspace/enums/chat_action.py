from enum import StrEnum


class ChatAction(StrEnum):
    """Chat action indicator (``bot.send_actions()``).

    - ``TYPING`` — "Bot is typing..." indicator.
    - ``LOOKING`` — "Bot is looking at the chat..." indicator.
    """

    TYPING = "typing"
    LOOKING = "looking"
