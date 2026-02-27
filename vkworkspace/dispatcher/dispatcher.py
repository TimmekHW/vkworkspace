from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from typing import Any

from ..enums.event_type import EventType
from ..types.callback_query import CallbackQuery
from ..types.chat_member_event import (
    ChangedChatInfoEvent,
    LeftChatMembersEvent,
    NewChatMembersEvent,
)
from ..types.event import Update
from ..types.message import Message
from .event.bases import UNHANDLED
from .router import Router

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
    """Root router + polling loop + FSM injection.

    The Dispatcher is the entry point of the framework. It receives raw
    events from ``bot.get_events()``, resolves them into typed objects
    (``Message``, ``CallbackQuery``, etc.), injects FSM context, and
    propagates through the router tree.

    Usage::

        dp = Dispatcher()                              # basic
        dp = Dispatcher(storage=MemoryStorage())       # explicit storage
        dp = Dispatcher(session_timeout=300)           # auto-clear FSM after 5 min

        dp.include_router(my_router)
        await dp.start_polling(bot)

    Features:
        - Long-polling with auto-reconnect and exponential backoff
        - FSM context injection (``state: FSMContext`` in handlers)
        - Session timeout (auto-clear stale FSM sessions)
        - Graceful shutdown on SIGINT/SIGTERM
        - ``is_running`` property for health checks
        - ``handle_signals=False`` for embedding in FastAPI / Quart
        - ``close_bot_on_stop=False`` for shared Bot instances

    Embedded in FastAPI::

        asyncio.create_task(
            dp.start_polling(bot, handle_signals=False, close_bot_on_stop=False)
        )
    """

    def __init__(
        self,
        storage: Any | None = None,
        fsm_strategy: str = "user_in_chat",
        name: str | None = None,
        handle_edited_as_message: bool = False,
        session_timeout: float | None = None,
    ) -> None:
        """
        Args:
            storage: FSM storage backend. Defaults to ``MemoryStorage()``.
                Use ``RedisStorage`` for multi-process deployments.
            fsm_strategy: FSM key strategy — ``"user_in_chat"`` (default)
                or ``"user"``.
            name: Router name (for logging).
            handle_edited_as_message: Route ``editedMessage`` events to
                ``@router.message()`` handlers (default ``False``).
            session_timeout: Auto-clear FSM state after N seconds of
                inactivity. ``None`` = never expire (default).
        """
        super().__init__(name=name or "Dispatcher")

        # Lazy import to avoid circular dependency
        if storage is None:
            from vkworkspace.fsm.storage.memory import MemoryStorage

            storage = MemoryStorage()

        self.storage = storage
        self.fsm_strategy = fsm_strategy
        self.handle_edited_as_message = handle_edited_as_message
        self.session_timeout = session_timeout
        self._running = False
        self._polling_tasks: list[asyncio.Task[None]] = []
        self._fsm_timestamps: dict[Any, float] = {}

    def _resolve_event(self, update: Update, bot: Any) -> tuple[str | None, Any, dict[str, Any]]:
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

        if update_type in (
            "message",
            "edited_message",
            "deleted_message",
            "pinned_message",
            "unpinned_message",
        ):
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

        if update_type == "new_chat_members":
            new_members = NewChatMembersEvent.model_validate(payload)
            new_members.set_bot(bot)
            return update_type, new_members, extra

        if update_type == "left_chat_members":
            left_members = LeftChatMembersEvent.model_validate(payload)
            left_members.set_bot(bot)
            return update_type, left_members, extra

        if update_type == "changed_chat_info":
            chat_info = ChangedChatInfoEvent.model_validate(payload)
            chat_info.set_bot(bot)
            return update_type, chat_info, extra

        return None, None, {}

    async def feed_update(self, bot: Any, update: Update) -> Any:
        update_type, event, extra = self._resolve_event(update, bot)
        if update_type is None:
            return UNHANDLED

        from_user = getattr(event, "from_user", None)
        logger.debug("Event: %s from %s", update_type, getattr(from_user, "user_id", "?"))

        # Inject FSM context
        from vkworkspace.fsm.context import FSMContext
        from vkworkspace.fsm.storage.base import StorageKey

        chat = getattr(event, "chat", None)
        from_user = getattr(event, "from_user", None)
        chat_id = getattr(chat, "chat_id", "") if chat else ""
        user_id = getattr(from_user, "user_id", "") if from_user else ""

        key: StorageKey | None = None
        if chat_id or user_id:
            key = StorageKey(
                bot_id=bot.token[:16],
                chat_id=chat_id,
                user_id=user_id,
            )
            fsm_context = FSMContext(storage=self.storage, key=key)
            current_state = await fsm_context.get_state()

            # Session timeout: clear expired FSM sessions
            if (
                current_state is not None
                and self.session_timeout is not None
                and key in self._fsm_timestamps
                and time.monotonic() - self._fsm_timestamps[key] > self.session_timeout
            ):
                await fsm_context.clear()
                del self._fsm_timestamps[key]
                current_state = None

            extra["state"] = fsm_context
            extra["current_state"] = current_state
        else:
            extra["state"] = None
            extra["current_state"] = None

        try:
            result = await self.propagate_event(
                update_type=update_type,
                event=event,
                **extra,
            )
        except Exception as e:
            logger.exception("Error processing update: %s", e)
            try:
                result = await self.propagate_event(
                    update_type="error",
                    event=e,
                    **extra,
                )
            except Exception:
                return UNHANDLED

        # Update FSM session timestamp after handler
        if key is not None and self.session_timeout is not None:
            new_state = await self.storage.get_state(key=key)
            if new_state is not None:
                self._fsm_timestamps[key] = time.monotonic()
            elif key in self._fsm_timestamps:
                del self._fsm_timestamps[key]

        return result

    async def _polling(self, bot: Any) -> None:
        logger.info("Polling started")
        consecutive_errors = 0
        while self._running:
            try:
                updates = await bot.get_events()
                if consecutive_errors:
                    logger.info("Connection restored after %d retries", consecutive_errors)
                consecutive_errors = 0
                for update in updates:
                    await self.feed_update(bot, update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                delay = min(2**consecutive_errors, 60)
                msg = "Polling error (%d): %s — retrying in %ds"
                if consecutive_errors == 1:
                    logger.warning(msg, consecutive_errors, e, delay, exc_info=True)
                elif consecutive_errors <= 3:
                    logger.warning(msg, consecutive_errors, e, delay)
                else:
                    logger.debug(msg, consecutive_errors, e, delay)
                await asyncio.sleep(delay)

    async def start_polling(
        self,
        *bots: Any,
        skip_updates: bool = False,
        handle_signals: bool = True,
        close_bot_on_stop: bool = True,
    ) -> None:
        """Start long-polling for one or more bots.

        Blocks until stopped by SIGINT/SIGTERM or ``dp.stop()``.
        Auto-reconnects on network errors with exponential backoff
        (2s → 4s → 8s → … → 60s max).

        Args:
            *bots: One or more ``Bot`` instances to poll.
            skip_updates: Discard pending updates on startup (default False).
            handle_signals: Register SIGINT/SIGTERM handlers (default True).
                Set ``False`` when running as a background task inside
                another framework (FastAPI, Quart) that manages signals.
            close_bot_on_stop: Close bot sessions on stop (default True).
                Set ``False`` when sharing a ``Bot`` instance with other
                parts of your app (e.g. FastAPI endpoints).

        Example::

            bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
            dp = Dispatcher()
            dp.include_router(router)
            await dp.start_polling(bot)

        Embedded in FastAPI::

            asyncio.create_task(
                dp.start_polling(bot, handle_signals=False, close_bot_on_stop=False)
            )
        """
        self._running = True

        await self.emit_startup()

        try:
            if handle_signals:
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    with contextlib.suppress(NotImplementedError):
                        loop.add_signal_handler(sig, self._stop_signal)

            if skip_updates:
                for bot in bots:
                    await bot.get_events(poll_time=0)

            self._polling_tasks = [asyncio.create_task(self._polling(bot)) for bot in bots]
            await asyncio.gather(*self._polling_tasks)
        except asyncio.CancelledError:
            logger.info("Polling cancelled")
        finally:
            self._running = False
            await self.emit_shutdown()
            if close_bot_on_stop:
                for bot in bots:
                    await bot.close()

    def _stop_signal(self) -> None:
        logger.info("Received stop signal")
        self._running = False
        for task in self._polling_tasks:
            task.cancel()

    @property
    def is_running(self) -> bool:
        """Whether the dispatcher is currently polling."""
        return self._running

    async def stop(self) -> None:
        """Stop polling gracefully."""
        self._running = False
        for task in self._polling_tasks:
            task.cancel()
