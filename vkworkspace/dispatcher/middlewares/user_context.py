from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .base import BaseMiddleware


class UserContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        chat = getattr(event, "chat", None)
        if chat is not None:
            data["chat"] = chat

        from_user = getattr(event, "from_user", None)
        if from_user is not None:
            data["from_user"] = from_user

        message = getattr(event, "message", None)
        if message is not None:
            data["callback_message"] = message

        return await handler(event, data)
