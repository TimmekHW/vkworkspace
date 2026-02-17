from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseFilter(ABC):
    """Base class for custom filters.

    Subclass and implement ``__call__`` to create your own filter.
    Return ``True``/``False``, or a ``dict`` to inject extra kwargs into
    the handler.

    Supports combining with operators: ``&`` (and), ``|`` (or), ``~`` (not).

    Example::

        class IsAdmin(BaseFilter):
            async def __call__(self, event, **kwargs) -> bool:
                admins = await event.bot.get_chat_admins(event.chat.chat_id)
                return any(a.user_id == event.from_user.user_id for a in admins)

        # Combining filters
        @router.message(IsAdmin() & Command("ban"))
        @router.message(IsAdmin() | IsModerator())
        @router.message(~IsAdmin())  # NOT admin
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
