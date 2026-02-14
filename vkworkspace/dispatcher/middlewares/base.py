from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any


class BaseMiddleware(ABC):
    """
    Base class for middleware.

    Usage::

        class LoggingMiddleware(BaseMiddleware):
            async def __call__(
                self,
                handler: Callable,
                event: Any,
                data: dict[str, Any],
            ) -> Any:
                print(f"Before: {event}")
                result = await handler(event, data)
                print(f"After: {result}")
                return result
    """

    @abstractmethod
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any: ...
