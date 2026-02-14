from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from .event.bases import UNHANDLED
from .router import Router
from ..enums.event_type import EventType
from ..types.base import VKTeamsObject
from ..types.callback_query import CallbackQuery
from ..types.event import Update
from ..types.message import Message

logger = logging.getLogger(__name__)

EVENT_TYPE_MAP: dict[str, str] = {
    EventType.NEW_MESSAGE: "message",
    EventType.EDITED_MESSAGE: "edited_message",
    EventType.DELETED_MESSAGE: "deleted_message",
    EventType.PINNED_MESSAGE: "pinned_message",
    EventType.UNPINNED_MESSAGE: "unpinned_message",
    EventType.NEW_CHAT_MEMBERS: "new_chat_members",
    EventType.LEFT_CHAT_MEMBERS: "left_chat_members",
    EventType.CHANGED_CHAT_INFO: "changed_chat_info",
    EventType.CALLBACK_QUERY: "callback_query",
}


class Dispatcher(Router):
    """
    Root router + polling loop + middleware chain.

    Usage::

        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(my_router)
        await dp.start_polling(bot)
    """

    def __init__(
        self,
        storage: Any | None = None,
        fsm_strategy: str = "user_in_chat",
        name: str | None = None,
        handle_edited_as_message: bool = False,
    ) -> None:
        super().__init__(name=name or "Dispatcher")

        # Lazy import to avoid circular dependency
        if storage is None:
            from vkworkspace.fsm.storage.memory import MemoryStorage

            storage = MemoryStorage()

        self.storage = storage
        self.fsm_strategy = fsm_strategy
        self.handle_edited_as_message = handle_edited_as_message
        self._running = False

    def _resolve_event(
        self, update: Update, bot: Any
    ) -> tuple[str | None, Any, dict[str, Any]]:
        payload = update.payload
        update_type = EVENT_TYPE_MAP.get(update.type)

        if update_type is None:
            logger.warning("Unknown event type: %s", update.type)
            return None, None, {}

        extra: dict[str, Any] = {
            "bot": bot,
            "raw_event": update,
            "event_type": update.type,
        }

        if update_type in ("message", "edited_message", "deleted_message",
                           "pinned_message", "unpinned_message"):
            msg = Message.model_validate(payload)
            msg.set_bot(bot)
            # Route edited messages to "message" handlers when flag is set
            if update_type == "edited_message" and self.handle_edited_as_message:
                return "message", msg, extra
            return update_type, msg, extra

        if update_type == "callback_query":
            cb = CallbackQuery.model_validate(payload)
            cb.set_bot(bot)
            if cb.message:
                cb.message.set_bot(bot)
            return update_type, cb, extra

        if update_type in ("new_chat_members", "left_chat_members", "changed_chat_info"):
            obj = VKTeamsObject.model_validate(payload)
            obj.set_bot(bot)
            return update_type, obj, extra

        return None, None, {}

    async def feed_update(self, bot: Any, update: Update) -> Any:
        update_type, event, extra = self._resolve_event(update, bot)
        if update_type is None:
            return UNHANDLED

        # Inject FSM context
        from vkworkspace.fsm.context import FSMContext
        from vkworkspace.fsm.storage.base import StorageKey

        chat = getattr(event, "chat", None)
        from_user = getattr(event, "from_user", None)
        chat_id = getattr(chat, "chat_id", "") if chat else ""
        user_id = getattr(from_user, "user_id", "") if from_user else ""

        if chat_id or user_id:
            key = StorageKey(
                bot_id=bot.token[:16],
                chat_id=chat_id,
                user_id=user_id,
            )
            fsm_context = FSMContext(storage=self.storage, key=key)
            current_state = await fsm_context.get_state()
            extra["state"] = fsm_context
            extra["current_state"] = current_state
        else:
            extra["state"] = None
            extra["current_state"] = None

        try:
            return await self.propagate_event(
                update_type=update_type,
                event=event,
                **extra,
            )
        except Exception as e:
            logger.exception("Error processing update: %s", e)
            try:
                return await self.propagate_event(
                    update_type="error",
                    event=e,
                    **extra,
                )
            except Exception:
                return UNHANDLED

    async def _polling(self, bot: Any) -> None:
        logger.info("Polling started")
        while self._running:
            try:
                updates = await bot.get_events()
                for update in updates:
                    await self.feed_update(bot, update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Polling error: %s", e)
                await asyncio.sleep(1)

    async def start_polling(
        self,
        *bots: Any,
        skip_updates: bool = False,
    ) -> None:
        """Start long-polling for one or more bots."""
        self._running = True

        await self.emit_startup()

        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._stop_signal)
                except NotImplementedError:
                    pass  # Windows

            if skip_updates:
                for bot in bots:
                    await bot.get_events(poll_time=0)

            tasks = [asyncio.create_task(self._polling(bot)) for bot in bots]
            await asyncio.gather(*tasks)
        finally:
            self._running = False
            await self.emit_shutdown()
            for bot in bots:
                await bot.close()

    def _stop_signal(self) -> None:
        logger.info("Received stop signal")
        self._running = False

    async def stop(self) -> None:
        self._running = False
