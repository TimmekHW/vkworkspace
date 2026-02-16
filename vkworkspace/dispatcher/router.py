from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from .event.bases import UNHANDLED
from .event.observer import EventObserver

logger = logging.getLogger(__name__)


class Router:
    """
    Handler registration hub. Mirrors aiogram 3's Router.

    Usage::

        router = Router(name="my_router")

        @router.message(Command("start"))
        async def start(message: Message):
            await message.answer("Hello!")

        @router.callback_query(F.callback_data == "action")
        async def callback(query: CallbackQuery):
            await query.answer("Done!")
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__
        self._sub_routers: list[Router] = []
        self._parent_router: Router | None = None

        # Event observers
        self.message = EventObserver(router=self, event_name="message")
        self.edited_message = EventObserver(router=self, event_name="edited_message")
        self.deleted_message = EventObserver(router=self, event_name="deleted_message")
        self.pinned_message = EventObserver(router=self, event_name="pinned_message")
        self.unpinned_message = EventObserver(router=self, event_name="unpinned_message")
        self.new_chat_members = EventObserver(router=self, event_name="new_chat_members")
        self.left_chat_members = EventObserver(router=self, event_name="left_chat_members")
        self.changed_chat_info = EventObserver(router=self, event_name="changed_chat_info")
        self.callback_query = EventObserver(router=self, event_name="callback_query")
        self.error = EventObserver(router=self, event_name="error")

        self.observers: dict[str, EventObserver] = {
            "message": self.message,
            "edited_message": self.edited_message,
            "deleted_message": self.deleted_message,
            "pinned_message": self.pinned_message,
            "unpinned_message": self.unpinned_message,
            "new_chat_members": self.new_chat_members,
            "left_chat_members": self.left_chat_members,
            "changed_chat_info": self.changed_chat_info,
            "callback_query": self.callback_query,
            "error": self.error,
        }

        self._on_startup: list[Callable[..., Any]] = []
        self._on_shutdown: list[Callable[..., Any]] = []

    def include_router(self, router: Router) -> None:
        if router._parent_router is not None:
            raise RuntimeError(
                f"Router '{router.name}' is already included in "
                f"router '{router._parent_router.name}'"
            )
        router._parent_router = self
        self._sub_routers.append(router)

    def include_routers(self, *routers: Router) -> None:
        for router in routers:
            self.include_router(router)

    async def propagate_event(
        self,
        update_type: str,
        event: Any,
        **kwargs: Any,
    ) -> Any:
        observer = self.observers.get(update_type)
        if observer is None:
            return UNHANDLED

        sub_routers = self._sub_routers

        async def _inner(ev: Any, data: dict[str, Any]) -> Any:
            result = await observer.trigger(ev, **data)
            if result is not UNHANDLED:
                return result
            for sub_router in sub_routers:
                result = await sub_router.propagate_event(
                    update_type=update_type,
                    event=ev,
                    **data,
                )
                if result is not UNHANDLED:
                    return result
            return UNHANDLED

        wrapped: Any = _inner
        for mw in reversed(observer.middleware.middlewares):

            def _make_wrapper(
                middleware: Any,
                prev: Any,
            ) -> Any:
                async def _call(ev: Any, data: dict[str, Any]) -> Any:
                    return await middleware(prev, ev, data)

                return _call

            wrapped = _make_wrapper(mw, wrapped)

        return await wrapped(event, kwargs)

    def on_startup(
        self, callback: Callable[..., Any] | None = None
    ) -> Any:
        if callback:
            self._on_startup.append(callback)
            return callback

        def decorator(cb: Callable[..., Any]) -> Callable[..., Any]:
            self._on_startup.append(cb)
            return cb

        return decorator

    def on_shutdown(
        self, callback: Callable[..., Any] | None = None
    ) -> Any:
        if callback:
            self._on_shutdown.append(callback)
            return callback

        def decorator(cb: Callable[..., Any]) -> Callable[..., Any]:
            self._on_shutdown.append(cb)
            return cb

        return decorator

    async def emit_startup(self) -> None:
        for cb in self._on_startup:
            if asyncio.iscoroutinefunction(cb):
                await cb()
            else:
                cb()
        for sub in self._sub_routers:
            await sub.emit_startup()

    async def emit_shutdown(self) -> None:
        for cb in self._on_shutdown:
            if asyncio.iscoroutinefunction(cb):
                await cb()
            else:
                cb()
        for sub in self._sub_routers:
            await sub.emit_shutdown()
