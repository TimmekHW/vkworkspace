from enum import StrEnum


class ChatType(StrEnum):
    """VK Teams chat type. Use with ``ChatTypeFilter``.

    Example::

        @router.message(ChatTypeFilter(ChatType.PRIVATE))
    """

    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
