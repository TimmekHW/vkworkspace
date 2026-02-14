from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseFilter(ABC):
    """
    Base class for all filters.

    Usage::

        class IsAdmin(BaseFilter):
            async def __call__(self, message: Message, **kwargs) -> bool:
                admins = await message.bot.get_chat_admins(message.chat.chat_id)
                return any(a.user_id == message.from_user.user_id for a in admins)
    """

    @abstractmethod
    async def __call__(self, event: Any, **kwargs: Any) -> bool | dict[str, Any]: ...

    def __invert__(self) -> _InvertedFilter:
        return _InvertedFilter(self)

    def __and__(self, other: BaseFilter) -> _AndFilter:
        return _AndFilter(self, other)

    def __or__(self, other: BaseFilter) -> _OrFilter:
        return _OrFilter(self, other)


class _InvertedFilter(BaseFilter):
    def __init__(self, original: BaseFilter) -> None:
        self._original = original

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        result = await self._original(event, **kwargs)
        return not result


class _AndFilter(BaseFilter):
    def __init__(self, left: BaseFilter, right: BaseFilter) -> None:
        self._left = left
        self._right = right

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        return bool(await self._left(event, **kwargs)) and bool(
            await self._right(event, **kwargs)
        )


class _OrFilter(BaseFilter):
    def __init__(self, left: BaseFilter, right: BaseFilter) -> None:
        self._left = left
        self._right = right

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        return bool(await self._left(event, **kwargs)) or bool(
            await self._right(event, **kwargs)
        )
