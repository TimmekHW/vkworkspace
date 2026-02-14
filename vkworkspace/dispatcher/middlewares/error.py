from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .base import BaseMiddleware
from ..event.bases import UNHANDLED, CancelHandler, SkipHandler

logger = logging.getLogger(__name__)


class ErrorsMiddleware(BaseMiddleware):
    def __init__(self, router: Any) -> None:
        self.router = router

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except (SkipHandler, CancelHandler):
            raise
        except Exception as e:
            logger.exception("Error in handler: %s", e)
            result = await self.router.propagate_event(
                update_type="error",
                event=e,
                **data,
            )
            if result is not UNHANDLED:
                return result
            raise
