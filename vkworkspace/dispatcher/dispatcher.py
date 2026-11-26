from __future__ import annotations

import asyncio
import contextlib
import logging
import random
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


class _Turn:
    """One update's place in the queue of its chat."""

    __slots__ = ("began", "began_at", "task")

    def __init__(self) -> None:
        self.began = asyncio.Event()
        self.began_at = 0.0
        self.task: asyncio.Task[None] | None = None


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
        - Every update in its own task, one chat at a time in arrival order
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
        self._handler_tasks: set[asyncio.Task[None]] = set()
        self._chat_tails: dict[str, _Turn] = {}
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

    # Longest pause between polling attempts while the server is unreachable.
    POLLING_BACKOFF_MAX = 5

    # A handler running longer than this no longer holds back the next updates
    # of its chat: a handler that never returns must not silence the chat.
    CHAT_ORDER_TIMEOUT = 60.0

    async def _polling(
        self,
        bot: Any,
        handle_as_tasks: bool = True,
        tasks_concurrency_limit: int | None = None,
        tasks_shutdown_timeout: float | None = 10.0,
    ) -> None:
        logger.info("Polling started")
        semaphore = (
            asyncio.Semaphore(tasks_concurrency_limit)
            if handle_as_tasks and tasks_concurrency_limit
            else None
        )
        consecutive_errors = 0
        failing_since = 0.0
        try:
            while self._running:
                try:
                    updates = await bot.get_events()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    consecutive_errors += 1
                    if consecutive_errors == 1:
                        failing_since = time.monotonic()
                    delay = min(2 ** (consecutive_errors - 1), self.POLLING_BACKOFF_MAX)
                    # Many bots that lost the same server do not all return at once.
                    delay *= random.uniform(0.5, 1.0)  # noqa: S311
                    self._log_polling_error(e, consecutive_errors, failing_since, delay)
                    await asyncio.sleep(delay)
                    continue

                if consecutive_errors:
                    logger.info(
                        "Connection restored after %d retries (%.0fs without events)",
                        consecutive_errors,
                        time.monotonic() - failing_since,
                    )
                    consecutive_errors = 0
                for update in updates:
                    if not handle_as_tasks:
                        await self._process_update(bot, update)
                        continue
                    if semaphore is not None:
                        # Polling waits while the limit is hit. The permit itself is
                        # taken by the handler when its turn comes: an update queued
                        # behind its own chat does not take a place from other chats.
                        await semaphore.acquire()
                        semaphore.release()
                    self._spawn_update(bot, update, semaphore)
                    if semaphore is not None:
                        await asyncio.sleep(0)  # let the new task take its permit
        except asyncio.CancelledError:
            pass
        finally:
            await self._wait_handler_tasks(tasks_shutdown_timeout)

    async def _process_update(self, bot: Any, update: Update) -> None:
        """``feed_update`` that never raises: a failed update is logged and dropped."""
        try:
            await self.feed_update(bot, update)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Update %s was not processed", update.event_id)

    @staticmethod
    def _order_key(update: Update) -> str | None:
        """Chat of the update: updates of one chat are handled in arrival order."""
        payload = update.payload
        chat = payload.get("chat")
        if not isinstance(chat, dict):
            message = payload.get("message")
            chat = message.get("chat") if isinstance(message, dict) else None
        chat_id = chat.get("chatId") if isinstance(chat, dict) else None
        return str(chat_id) if chat_id else None

    def _spawn_update(
        self, bot: Any, update: Update, semaphore: asyncio.Semaphore | None = None
    ) -> asyncio.Task[None]:
        """Handle *update* in its own task, after the previous update of the same chat."""
        key = self._order_key(update)
        previous = self._chat_tails.get(key) if key else None
        turn = _Turn()
        task = asyncio.create_task(
            self._handle_in_order(previous, turn, key, bot, update, semaphore)
        )
        turn.task = task
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_tasks.discard)
        if key:
            self._chat_tails[key] = turn

            def forget(_done: asyncio.Task[None], key: str = key) -> None:
                if self._chat_tails.get(key) is turn:
                    del self._chat_tails[key]

            task.add_done_callback(forget)
        return task

    async def _handle_in_order(
        self,
        previous: _Turn | None,
        turn: _Turn,
        chat_id: str | None,
        bot: Any,
        update: Update,
        semaphore: asyncio.Semaphore | None,
    ) -> None:
        try:
            if previous is not None:
                await self._wait_for_turn(previous, chat_id, update)
            async with semaphore if semaphore is not None else contextlib.nullcontext():
                turn.began_at = time.monotonic()
                turn.began.set()
                await self._process_update(bot, update)
        finally:
            turn.began.set()

    async def _wait_for_turn(self, previous: _Turn, chat_id: str | None, update: Update) -> None:
        """Wait until the previous update of the chat is handled.

        The wait ends early once the previous handler has been running for
        :attr:`CHAT_ORDER_TIMEOUT`: it is counted from the moment that handler
        started, so updates queued behind a stuck one still go in order.
        """
        task = previous.task
        if task is None or task.done():
            return
        began = asyncio.ensure_future(previous.began.wait())
        try:
            await asyncio.wait({task, began}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            began.cancel()
        if task.done():
            return
        remaining = previous.began_at + self.CHAT_ORDER_TIMEOUT - time.monotonic()
        if remaining > 0:
            await asyncio.wait({task}, timeout=remaining)
        if not task.done():
            logger.warning(
                "Chat %s: a handler has been running for more than %gs — "
                "update %s is handled without waiting for it",
                chat_id,
                self.CHAT_ORDER_TIMEOUT,
                update.event_id,
            )

    async def _wait_handler_tasks(self, timeout: float | None) -> None:
        """Let running handlers finish; cancel the ones still running after *timeout*.

        ``None`` = do not wait and do not cancel.
        """
        tasks = {t for t in self._handler_tasks if t is not asyncio.current_task()}
        if timeout is None or not tasks:
            return
        logger.info("Waiting up to %gs for %d update(s) being handled", timeout, len(tasks))
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        if not pending:
            return
        logger.warning(
            "%d update(s) were still being handled after %gs — cancelled", len(pending), timeout
        )
        for task in pending:
            task.cancel()
        await asyncio.wait(pending)

    @staticmethod
    def _log_polling_error(
        exc: Exception, consecutive_errors: int, failing_since: float, delay: float
    ) -> None:
        reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        msg = "Polling error (%d): %s — retrying in %.1fs"
        logger.warning(msg, consecutive_errors, reason, delay, exc_info=consecutive_errors == 1)
        if consecutive_errors % 10 == 0:
            logger.error(
                "No events for %.0fs: %d polling errors in a row, last: %s",
                time.monotonic() - failing_since,
                consecutive_errors,
                reason,
            )

    async def start_polling(
        self,
        *bots: Any,
        skip_updates: bool = False,
        handle_signals: bool = True,
        close_bot_on_stop: bool = True,
        handle_as_tasks: bool = True,
        tasks_concurrency_limit: int | None = None,
        tasks_shutdown_timeout: float | None = 10.0,
    ) -> None:
        """Start long-polling for one or more bots.

        Blocks until stopped by SIGINT/SIGTERM or ``dp.stop()``.
        Auto-reconnects on network errors and HTTP errors of the server with
        exponential backoff (up to 1s → 2s → 4s → 5s). Every failed attempt is
        logged.

        Args:
            *bots: One or more ``Bot`` instances to poll.
            skip_updates: Discard pending updates on startup (default False).
            handle_signals: Register SIGINT/SIGTERM handlers (default True).
                Set ``False`` when running as a background task inside
                another framework (FastAPI, Quart) that manages signals.
            close_bot_on_stop: Close bot sessions on stop (default True).
                Set ``False`` when sharing a ``Bot`` instance with other
                parts of your app (e.g. FastAPI endpoints).
            handle_as_tasks: Handle every update in its own task (default
                True): a slow or stuck handler does not delay polling or
                other chats. Updates of one chat are still handled one by
                one, in arrival order; a handler running longer than 60
                seconds (``Dispatcher.CHAT_ORDER_TIMEOUT``) stops holding back
                the next updates of its chat, so a handler that never returns
                does not silence the chat. ``False`` = handle updates inside
                the polling loop, one at a time.
            tasks_concurrency_limit: Most handlers running at once, per bot
                (``None`` = no limit). Polling waits while the limit is hit.
                An update waiting for the previous one of its chat does not
                count.
            tasks_shutdown_timeout: On stop, seconds to wait for running
                handlers before cancelling them (default 10). ``None`` =
                leave them running.

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

            self._polling_tasks = [
                asyncio.create_task(
                    self._polling(
                        bot,
                        handle_as_tasks=handle_as_tasks,
                        tasks_concurrency_limit=tasks_concurrency_limit,
                        tasks_shutdown_timeout=tasks_shutdown_timeout,
                    )
                )
                for bot in bots
            ]
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
        # Remove custom handlers so next Ctrl+C force-kills the process
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.remove_signal_handler(sig)
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
