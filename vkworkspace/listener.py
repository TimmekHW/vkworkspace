"""Redis Stream listener for VK Teams bots.

Consume tasks from Redis Streams — reliable message queue with
acknowledgment, consumer groups, and dead letter handling.
Requires ``redis[hiredis]`` (same as FSM).

Usage::

    from vkworkspace.listener import RedisListener

    listener = RedisListener(
        token="TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
        redis_url="redis://localhost:6379",
    )

    @listener.handler("bot:tasks")
    async def on_task(bot, data):
        await bot.send_text(data["chat_id"], data["text"])
        # XACK sent automatically on success
        # on failure — message stays in pending, retried later

    listener.run()

    # PHP side:
    # $redis->xAdd("bot:tasks", "*", ["chat_id" => "user@corp.ru", "text" => "Hello!"]);

With Pydantic validation::

    from pydantic import BaseModel

    class TaskPayload(BaseModel):
        chat_id: str
        text: str

    @listener.handler("bot:tasks", model=TaskPayload)
    async def on_task(bot, data: TaskPayload):
        await bot.send_text(data.chat_id, data.text)

Lifecycle hooks::

    @listener.on_startup
    async def setup():
        logger.info("Listener starting...")

    @listener.on_shutdown
    async def cleanup():
        logger.info("Listener stopped")

With VK Teams event handlers (polling + Redis in one process)::

    from vkworkspace import Router
    from vkworkspace.filters import Command

    router = Router()

    @router.message(Command("status"))
    async def cmd_status(message):
        await message.answer("Listener is running!")

    listener.include_router(router)
    listener.run()  # Redis streams + VK Teams polling

Multiple streams::

    @listener.handler("bot:tasks")
    async def on_task(bot, data):
        await bot.send_text(data["chat_id"], data["text"])

    @listener.handler("bot:alerts")
    async def on_alert(bot, data):
        kb = InlineKeyboardBuilder()
        kb.button(text="ACK", callback_data="ack")
        await bot.send_text(data["chat_id"], data["text"],
                            inline_keyboard_markup=kb.as_markup())
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Any

from vkworkspace.client.bot import Bot

logger = logging.getLogger(__name__)

ListenerHandler = Callable[..., Awaitable[Any]]

_DEFAULT_GROUP = "vkworkspace-workers"
_DEFAULT_CONSUMER = "worker-1"


class RedisListener:
    """Consume Redis Streams and process messages with the Bot API.

    Uses Redis Streams with consumer groups for reliable delivery:

    - **XREADGROUP** — read new messages from a stream
    - **XACK** — acknowledge after successful processing
    - **Pending retry** — re-process messages that failed or timed out
    - **Dead letter** — move permanently failed messages to a separate stream

    Features:
        - Graceful shutdown on SIGINT/SIGTERM
        - ``on_startup`` / ``on_shutdown`` lifecycle hooks
        - Optional Pydantic model validation for incoming data
        - ``include_router()`` for VK Teams polling alongside Redis

    Args:
        redis_url: Redis connection URL (e.g. ``"redis://localhost:6379"``).
            Can also pass an existing ``redis.asyncio.Redis`` instance.
        token: Bot token. Not needed if ``bot`` is provided.
        api_url: VK Teams API URL. Not needed if ``bot`` is provided.
        bot: Existing :class:`Bot` instance. If provided, ``token``
            and ``api_url`` are ignored.
        group: Consumer group name (default ``"vkworkspace-workers"``).
        consumer: Consumer name within the group (default ``"worker-1"``).
            Use different names when running multiple bot instances.
        max_retries: Max delivery attempts before sending to dead letter
            stream (default ``3``).
        retry_after: Seconds before retrying a pending (unacked) message
            (default ``30``).
        block_ms: XREADGROUP block timeout in milliseconds (default ``5000``).
        **bot_kwargs: Extra arguments for :class:`Bot`
            (``proxy``, ``rate_limit``, etc.).
    """

    def __init__(
        self,
        redis_url: str | Any,
        token: str | None = None,
        api_url: str | None = None,
        bot: Bot | None = None,
        group: str = _DEFAULT_GROUP,
        consumer: str = _DEFAULT_CONSUMER,
        max_retries: int = 3,
        retry_after: float = 30.0,
        block_ms: int = 5000,
        **bot_kwargs: Any,
    ) -> None:
        if bot is not None:
            self.bot = bot
        elif token is not None and api_url is not None:
            self.bot = Bot(token=token, api_url=api_url, **bot_kwargs)
        else:
            msg = "Either 'bot' or both 'token' and 'api_url' are required"
            raise TypeError(msg)

        self._redis_url = redis_url
        self._redis: Any | None = None
        self.group = group
        self.consumer = consumer
        self.max_retries = max_retries
        self.retry_after = retry_after
        self.block_ms = block_ms
        self._running = False
        self._handlers: dict[str, tuple[ListenerHandler, type | None]] = {}
        self._on_startup: list[Callable[..., Any]] = []
        self._on_shutdown: list[Callable[..., Any]] = []
        self._dispatcher: Any | None = None

    # ── handler decorator ─────────────────────────────────────────────

    def handler(
        self,
        stream: str,
        model: type | None = None,
    ) -> Callable[[ListenerHandler], ListenerHandler]:
        """Register a handler for a Redis Stream.

        The handler receives ``(bot, data)`` where ``data`` is the stream
        message fields as a dict (or a model instance if ``model`` is set).
        If the handler completes without error, the message is acknowledged
        (XACK). If it raises, the message stays in pending and will be retried.

        Args:
            stream: Redis Stream name (e.g. ``"bot:tasks"``).
            model: Optional Pydantic model (or any class) for data validation.
                When set, raw dict is passed to ``model(**data)`` before
                calling the handler.

        Example::

            @listener.handler("bot:tasks")
            async def on_task(bot, data):
                await bot.send_text(data["chat_id"], data["text"])

        With validation::

            @listener.handler("bot:tasks", model=TaskPayload)
            async def on_task(bot, data: TaskPayload):
                await bot.send_text(data.chat_id, data.text)
        """
        def decorator(func: ListenerHandler) -> ListenerHandler:
            self._handlers[stream] = (func, model)
            return func

        return decorator

    # ── lifecycle hooks ────────────────────────────────────────────────

    def on_startup(
        self, callback: Callable[..., Any] | None = None,
    ) -> Any:
        """Register a startup hook. Runs before streams are consumed.

        Can be used as a decorator or called directly::

            @listener.on_startup
            async def setup():
                logger.info("Listener starting...")

            # or
            listener.on_startup(my_setup_function)
        """
        if callback:
            self._on_startup.append(callback)
            return callback

        def decorator(cb: Callable[..., Any]) -> Callable[..., Any]:
            self._on_startup.append(cb)
            return cb

        return decorator

    def on_shutdown(
        self, callback: Callable[..., Any] | None = None,
    ) -> Any:
        """Register a shutdown hook. Runs after streams stop.

        Example::

            @listener.on_shutdown
            async def cleanup():
                await db.close()
        """
        if callback:
            self._on_shutdown.append(callback)
            return callback

        def decorator(cb: Callable[..., Any]) -> Callable[..., Any]:
            self._on_shutdown.append(cb)
            return cb

        return decorator

    async def _emit_startup(self) -> None:
        for cb in self._on_startup:
            if asyncio.iscoroutinefunction(cb):
                await cb()
            else:
                cb()
        if self._dispatcher:
            await self._dispatcher.emit_startup()

    async def _emit_shutdown(self) -> None:
        for cb in self._on_shutdown:
            if asyncio.iscoroutinefunction(cb):
                await cb()
            else:
                cb()
        if self._dispatcher:
            await self._dispatcher.emit_shutdown()

    # ── VK Teams event handling ────────────────────────────────────────

    def include_router(self, router: Any, storage: Any | None = None) -> None:
        """Add VK Teams event handlers (enables polling alongside Redis).

        When at least one router is included, :meth:`start` runs both
        Redis stream consumers and ``Dispatcher`` polling concurrently.

        Args:
            router: A :class:`Router` with message/callback handlers.
            storage: FSM storage (default ``MemoryStorage()``).

        Example::

            router = Router()

            @router.message(Command("start"))
            async def start(message):
                await message.answer("Hello!")

            listener.include_router(router)
        """
        if self._dispatcher is None:
            from vkworkspace.dispatcher.dispatcher import Dispatcher
            from vkworkspace.fsm.storage.memory import MemoryStorage

            self._dispatcher = Dispatcher(storage=storage or MemoryStorage())
        self._dispatcher.include_router(router)

    # ── FSM access ─────────────────────────────────────────────────────

    def get_state(self, chat_id: str, user_id: str | None = None) -> Any:
        """Get :class:`FSMContext` for use in stream handlers.

        Bridges Redis stream handlers and bot event handlers — stream
        handler can set FSM state/data that callback/message handlers
        will read.

        Requires :meth:`include_router` to be called first (creates storage).

        Args:
            chat_id: Target chat ID.
            user_id: User ID (defaults to ``chat_id`` for DMs).

        Returns:
            :class:`FSMContext` instance.
        """
        if self._dispatcher is None:
            msg = "No router included. Call include_router() first."
            raise RuntimeError(msg)

        from vkworkspace.fsm.context import FSMContext
        from vkworkspace.fsm.storage.base import StorageKey

        key = StorageKey(
            bot_id=self.bot.token[:16],
            chat_id=chat_id,
            user_id=user_id or chat_id,
        )
        return FSMContext(storage=self._dispatcher.storage, key=key)

    # ── properties ─────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Whether the listener is currently running.

        Useful for health checks::

            if listener.is_running:
                return {"status": "ok"}
        """
        return self._running

    # ── Redis connection ──────────────────────────────────────────────

    async def _get_redis(self) -> Any:
        if self._redis is not None:
            return self._redis

        if not isinstance(self._redis_url, str):
            self._redis = self._redis_url
            return self._redis

        from redis.asyncio import Redis

        self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def _ensure_group(self, redis: Any, stream: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await redis.xgroup_create(stream, self.group, id="0", mkstream=True)
            logger.info("Created consumer group '%s' on stream '%s'", self.group, stream)
        except Exception as exc:
            # BUSYGROUP = group already exists, that's fine
            if "BUSYGROUP" in str(exc):
                pass
            else:
                raise

    # ── process single message ────────────────────────────────────────

    async def _process_message(
        self,
        redis: Any,
        stream: str,
        msg_id: str,
        fields: dict[str, Any],
        func: ListenerHandler,
        model: type | None = None,
    ) -> None:
        """Run handler, XACK on success, leave pending on failure."""
        # Parse JSON values if they look like JSON
        data: dict[str, Any] = {}
        for k, v in fields.items():
            if isinstance(v, str) and v.startswith(("{", "[")):
                try:
                    data[k] = json.loads(v)
                except json.JSONDecodeError:
                    data[k] = v
            else:
                data[k] = v

        try:
            validated: Any = model(**data) if model is not None else data
            await func(self.bot, validated)
            await redis.xack(stream, self.group, msg_id)
            logger.debug("ACK %s:%s", stream, msg_id)
        except Exception:
            logger.exception("Handler failed for %s:%s — will retry", stream, msg_id)

    # ── main read loop ────────────────────────────────────────────────

    async def _read_loop(
        self,
        stream: str,
        func: ListenerHandler,
        model: type | None,
    ) -> None:
        """XREADGROUP loop — read new messages from stream."""
        redis = await self._get_redis()
        await self._ensure_group(redis, stream)

        logger.info(
            "Listening on stream '%s' (group=%s, consumer=%s)",
            stream, self.group, self.consumer,
        )

        while self._running:
            try:
                results = await redis.xreadgroup(
                    self.group,
                    self.consumer,
                    {stream: ">"},
                    count=10,
                    block=self.block_ms,
                )
                if not results:
                    continue

                for _stream_name, messages in results:
                    for msg_id, fields in messages:
                        await self._process_message(
                            redis, stream, msg_id, fields, func, model,
                        )

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Stream read error on '%s'", stream)
                await asyncio.sleep(1)

    # ── pending retry loop ────────────────────────────────────────────

    async def _pending_loop(
        self,
        stream: str,
        func: ListenerHandler,
        model: type | None,
    ) -> None:
        """Check for unacked messages and retry or move to dead letter."""
        redis = await self._get_redis()
        dead_letter = f"{stream}:dead"

        while self._running:
            try:
                await asyncio.sleep(self.retry_after)

                if not self._running:
                    break

                # Get pending messages for this consumer
                pending = await redis.xpending_range(
                    stream, self.group,
                    min="-", max="+",
                    count=100,
                    consumername=self.consumer,
                )

                if not pending:
                    continue

                for entry in pending:
                    msg_id = entry["message_id"]
                    delivery_count = entry["times_delivered"]
                    idle_ms = entry["time_since_delivered"]

                    # Skip if not idle long enough
                    if idle_ms < self.retry_after * 1000:
                        continue

                    if delivery_count > self.max_retries:
                        # Dead letter: move message data, then ack
                        msgs = await redis.xrange(stream, min=msg_id, max=msg_id)
                        if msgs:
                            _, fields = msgs[0]
                            fields["_original_stream"] = stream
                            fields["_original_id"] = msg_id
                            fields["_delivery_count"] = str(delivery_count)
                            await redis.xadd(dead_letter, fields)
                            logger.warning(
                                "Dead letter: %s:%s → %s (after %d attempts)",
                                stream, msg_id, dead_letter, delivery_count,
                            )
                        await redis.xack(stream, self.group, msg_id)
                        continue

                    # Retry: claim and re-process
                    claimed = await redis.xclaim(
                        stream, self.group, self.consumer,
                        min_idle_time=int(self.retry_after * 1000),
                        message_ids=[msg_id],
                    )

                    for claimed_id, fields in claimed:
                        if fields:
                            logger.info(
                                "Retrying %s:%s (attempt %d/%d)",
                                stream, claimed_id, delivery_count, self.max_retries,
                            )
                            await self._process_message(
                                redis, stream, claimed_id, fields, func, model,
                            )

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Pending check error on '%s'", stream)
                await asyncio.sleep(self.retry_after)

    # ── start / stop / run ────────────────────────────────────────────

    async def start(self) -> None:
        """Start all stream listeners (async).

        For each registered stream, starts two tasks:

        - **read loop** — XREADGROUP for new messages
        - **pending loop** — retry unacked messages, dead letter

        If routers were added via :meth:`include_router`, also starts
        VK Teams long-polling in the same event loop.

        Registers SIGINT/SIGTERM handlers for graceful shutdown.

        Use inside an existing event loop::

            asyncio.create_task(listener.start())
        """
        if not self._handlers:
            msg = "No handlers registered. Use @listener.handler() to add at least one."
            raise RuntimeError(msg)

        self._running = True

        tasks: list[asyncio.Task[None]] = []
        try:
            await self._emit_startup()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, self._stop_signal)

            for stream, (func, model) in self._handlers.items():
                tasks.append(asyncio.create_task(self._read_loop(stream, func, model)))
                tasks.append(asyncio.create_task(self._pending_loop(stream, func, model)))

            if self._dispatcher:
                self._dispatcher._running = True
                tasks.append(asyncio.create_task(self._dispatcher._polling(self.bot)))
                logger.info("Polling enabled — bot handlers will receive VK Teams events")

            logger.info(
                "RedisListener started: %s",
                ", ".join(self._handlers.keys()),
            )

            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Listener cancelled")
        finally:
            self._running = False
            for t in tasks:
                if not t.done():
                    t.cancel()
            await self._emit_shutdown()
            await self.bot.close()

    def stop(self) -> None:
        """Stop the listener gracefully.

        Sets the running flag to ``False``. All loops will exit
        after their current iteration (max ``block_ms`` delay).
        """
        self._running = False
        if self._dispatcher:
            self._dispatcher._running = False

    def _stop_signal(self) -> None:
        logger.info("Received stop signal")
        self.stop()

    def run(self) -> None:
        """Start the listener (blocking).

        Convenience wrapper around ``asyncio.run(listener.start())``.
        """
        asyncio.run(self.start())
