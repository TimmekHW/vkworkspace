from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .bases import UNHANDLED, CancelHandler, SkipHandler
from .handler import FilterObject, HandlerObject
from ..middlewares.manager import MiddlewareManager

logger = logging.getLogger(__name__)


class EventObserver:
    """
    Manages handlers for a specific event type.

    Usage::

        observer = EventObserver(router=router, event_name="message")

        @observer(Command("start"))
        async def my_handler(message: Message):
            ...
    """

    def __init__(self, router: Any, event_name: str) -> None:
        self.router = router
        self.event_name = event_name
        self.handlers: list[HandlerObject] = []
        self.middleware = MiddlewareManager()
        self.outer_middleware = MiddlewareManager()

    def register(
        self,
        callback: Callable[..., Awaitable[Any]],
        *filters: Any,
        flags: dict[str, Any] | None = None,
    ) -> Callable[..., Awaitable[Any]]:
        filter_objects = [FilterObject(callback=f) for f in filters] or None
        handler = HandlerObject(
            callback=callback,
            filters=filter_objects,
            flags=flags or {},
        )
        self.handlers.append(handler)
        return callback

    def __call__(
        self,
        *filters: Any,
        flags: dict[str, Any] | None = None,
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        def decorator(
            callback: Callable[..., Awaitable[Any]],
        ) -> Callable[..., Awaitable[Any]]:
            self.register(callback, *filters, flags=flags)
            return callback

        return decorator

    async def trigger(self, event: Any, **kwargs: Any) -> Any:
        for handler in self.handlers:
            kwargs_copy = dict(kwargs)
            check_result, updated_kwargs = await handler.check(event, kwargs_copy)
            if check_result:
                try:
                    return await handler.call(event, **updated_kwargs)
                except SkipHandler:
                    continue
                except CancelHandler:
                    break
        return UNHANDLED

    async def propagate(self, event: Any, **kwargs: Any) -> Any:
        async def _process(ev: Any, data: dict[str, Any]) -> Any:
            return await self.trigger(ev, **data)

        wrapped = _process
        for mw in reversed(self.middleware.middlewares):

            def _make_wrapper(
                middleware: Any,
                prev: Callable[..., Any],
            ) -> Callable[..., Any]:
                async def _call(ev: Any, data: dict[str, Any]) -> Any:
                    return await middleware(prev, ev, data)

                return _call

            wrapped = _make_wrapper(mw, wrapped)

        return await wrapped(event, kwargs)
