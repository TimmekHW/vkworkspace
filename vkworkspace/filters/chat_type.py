from __future__ import annotations

from typing import Any

from ..enums.chat_type import ChatType
from .base import BaseFilter


class ChatTypeFilter(BaseFilter):
    """
    Filter by chat type.

    Usage::

        @router.message(ChatTypeFilter(ChatType.PRIVATE))
        @router.message(ChatTypeFilter("group"))
        @router.message(ChatTypeFilter(["private", "group"]))
    """

    def __init__(self, chat_type: ChatType | str | list[str]) -> None:
        if isinstance(chat_type, (list, tuple)):
            self.chat_types = [str(t) for t in chat_type]
        else:
            self.chat_types = [str(chat_type)]

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        chat = getattr(event, "chat", None)
        if chat is None:
            return False
        return getattr(chat, "type", None) in self.chat_types
