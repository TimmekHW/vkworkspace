"""HTTP server for VK Teams bots.

Run a bot as an HTTP service — accept requests from any system,
send messages, handle bot events. Zero extra dependencies:
asyncio (stdlib) for the server, httpx (already in framework) for the API.

Standalone server::

    from vkworkspace.server import BotServer

    server = BotServer(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")

    @server.route("/send")
    async def send(bot, data):
        await bot.send_text(data["email"], data["text"])

    server.run(port=8080)

Server + bot handlers (HTTP + polling in one process)::

    from vkworkspace import Router, F
    from vkworkspace.server import BotServer
    from vkworkspace.filters import Command

    server = BotServer(token="TOKEN", api_url="...")

    router = Router()

    @router.message(Command("start"))
    async def start(message):
        await message.answer("Hello!")

    @server.route("/notify")
    async def notify(bot, data):
        await bot.send_text(data["email"], data["text"])

    server.include_router(router)
    server.run(port=8080)  # HTTP server + VK Teams polling

Lifecycle hooks::

    @server.on_startup
    async def setup():
        logger.info("Server starting...")

    @server.on_shutdown
    async def cleanup():
        await db.close()

Embed into existing async app::

    # In your FastAPI / Quart startup:
    asyncio.create_task(server.start())
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from vkworkspace.client.bot import Bot

logger = logging.getLogger(__name__)

RouteHandler = Callable[[Bot, dict[str, Any]], Awaitable[dict[str, Any] | None]]

_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
}


class BotServer:
    """HTTP server for integrating non-Python systems with VK Teams bots.

    **Not a webhook receiver.** BotServer exposes HTTP endpoints so that
    external systems (PHP, Go, N8N, Grafana, Zabbix — any language) can
    call the bot via simple HTTP requests. For Python apps, use :class:`Bot`
    directly — no server needed.

    Combines an asyncio-based HTTP server with the framework's :class:`Bot`.
    Any external system sends an HTTP request — the server processes it
    using ``Bot`` methods.

    Optionally, call :meth:`include_router` to also handle VK Teams events
    (messages, callbacks, FSM) via long-polling — both run in a single process.

    Features:
        - Graceful shutdown on SIGINT/SIGTERM
        - ``on_startup`` / ``on_shutdown`` lifecycle hooks
        - ``include_router()`` for VK Teams polling alongside HTTP
        - ``get_state()`` for FSM access from route handlers

    Args:
        token: Bot token from BotFather.
        api_url: VK Teams API base URL.
        host: Bind address (default ``"0.0.0.0"``).
        port: Bind port (default ``8080``).
        api_key: Optional ``X-Api-Key`` header for request authentication.
        **bot_kwargs: Extra arguments for :class:`Bot`
            (``proxy``, ``rate_limit``, ``parse_mode``, ``retry_on_5xx``, etc.).
    """

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.icq.net/bot/v1",
        host: str = "0.0.0.0",
        port: int = 8080,
        api_key: str | None = None,
        **bot_kwargs: Any,
    ) -> None:
        self.bot = Bot(token=token, api_url=api_url, **bot_kwargs)
        self.host = host
        self.port = port
        self.api_key = api_key
        self._routes: dict[str, tuple[set[str], RouteHandler]] = {}
        self._dispatcher: Any | None = None
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._on_startup: list[Callable[..., Any]] = []
        self._on_shutdown: list[Callable[..., Any]] = []

    # ── route decorator ───────────────────────────────────────────────

    def route(
        self,
        path: str,
        methods: list[str] | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Register an HTTP endpoint.

        Args:
            path: URL path (e.g. ``"/send"``, ``"/alert"``).
            methods: Allowed HTTP methods (default ``["POST"]``).

        The handler receives ``(bot, data)`` where ``data`` is:

        - **POST**: parsed JSON body
        - **GET**: query parameters as dict

        Return a dict (sent as JSON) or ``None`` (``{"ok": true}``).

        Example::

            @server.route("/send")
            async def send(bot, data):
                await bot.send_text(data["email"], data["text"])

            @server.route("/status", methods=["GET"])
            async def status(bot, data):
                return {"ok": True, "version": "1.0"}
        """
        allowed = {m.upper() for m in (methods or ["POST"])}

        def decorator(func: RouteHandler) -> RouteHandler:
            self._routes[path] = (allowed, func)
            return func

        return decorator

    # ── lifecycle hooks ────────────────────────────────────────────────

    def on_startup(
        self, callback: Callable[..., Any] | None = None,
    ) -> Any:
        """Register a startup hook. Runs before the server starts accepting.

        Can be used as a decorator or called directly::

            @server.on_startup
            async def setup():
                logger.info("Server starting...")

            # or
            server.on_startup(my_setup_function)
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
        """Register a shutdown hook. Runs after the server stops.

        Example::

            @server.on_shutdown
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

    # ── VK Teams event handling ───────────────────────────────────────

    def include_router(self, router: Any, storage: Any | None = None) -> None:
        """Add VK Teams event handlers (enables polling alongside HTTP).

        When at least one router is included, :meth:`start` runs both
        the HTTP server and ``Dispatcher`` polling concurrently.

        Args:
            router: A :class:`Router` with message/callback handlers.
            storage: FSM storage (default ``MemoryStorage()``).

        Example::

            router = Router()

            @router.message(Command("start"))
            async def start(message):
                await message.answer("Hello!")

            server.include_router(router)
        """
        if self._dispatcher is None:
            from vkworkspace.dispatcher.dispatcher import Dispatcher
            from vkworkspace.fsm.storage.memory import MemoryStorage

            self._dispatcher = Dispatcher(storage=storage or MemoryStorage())
        self._dispatcher.include_router(router)

    # ── FSM access from routes ─────────────────────────────────────────

    def get_state(self, chat_id: str, user_id: str | None = None) -> Any:
        """Get :class:`FSMContext` for use in route handlers.

        Bridges HTTP routes and bot event handlers — route handler can
        set FSM state/data that callback/message handlers will read.

        Requires :meth:`include_router` to be called first (creates storage).

        Args:
            chat_id: Target chat ID.
            user_id: User ID (defaults to ``chat_id`` for DMs).

        Returns:
            :class:`FSMContext` instance.

        Example::

            @server.route("/start-survey")
            async def start_survey(bot, data):
                state = server.get_state(chat_id=data["email"])
                await state.set_state(Survey.question_1)
                await bot.send_text(data["email"], "Как дела?")
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
        """Whether the server is currently running."""
        return self._running

    # ── HTTP parsing ──────────────────────────────────────────────────

    @staticmethod
    async def _read_request(
        reader: asyncio.StreamReader,
    ) -> tuple[str | None, str | None, dict[str, str], dict[str, str], bytes]:
        """Parse HTTP/1.1 request → (method, path, query, headers, body)."""
        request_line = await reader.readline()
        if not request_line:
            return None, None, {}, {}, b""

        parts = request_line.decode("utf-8", errors="replace").strip().split()
        if len(parts) < 2:
            return None, None, {}, {}, b""

        method = parts[0].upper()
        raw_url = parts[1]

        # Parse path and query string
        parsed = urlparse(raw_url)
        path = parsed.path
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        # Headers
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if ": " in decoded:
                key, value = decoded.split(": ", 1)
                headers[key.lower()] = value

        # Body
        content_length = int(headers.get("content-length", "0"))
        body = await reader.readexactly(content_length) if content_length > 0 else b""

        return method, path, query, headers, body

    @staticmethod
    def _write_response(
        writer: asyncio.StreamWriter,
        status: int,
        body: dict[str, Any],
    ) -> None:
        """Write HTTP/1.1 JSON response."""
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        header = (
            f"HTTP/1.1 {status} {_STATUS_TEXT.get(status, 'Error')}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        writer.write(header.encode("utf-8") + payload)

    # ── connection handler ────────────────────────────────────────────

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            method, path, query, headers, body = await self._read_request(reader)

            if method is None or path is None:
                return

            # Auth
            if self.api_key and headers.get("x-api-key", "") != self.api_key:
                    self._write_response(writer, 401, {"ok": False, "error": "unauthorized"})
                    await writer.drain()
                    return

            # Built-in: GET /health
            if path == "/health" and method == "GET":
                info: dict[str, Any] = {
                    "ok": True,
                    "routes": list(self._routes.keys()),
                    "polling": self._dispatcher is not None,
                }
                self._write_response(writer, 200, info)
                await writer.drain()
                return

            # Route lookup
            route_info = self._routes.get(path)
            if route_info is None:
                self._write_response(writer, 404, {
                    "ok": False,
                    "error": f"not found: {path}",
                    "routes": list(self._routes.keys()),
                })
                await writer.drain()
                return

            allowed_methods, handler = route_info

            # Method check
            if method not in allowed_methods:
                self._write_response(writer, 405, {
                    "ok": False,
                    "error": f"method {method} not allowed, "
                    f"use {', '.join(sorted(allowed_methods))}",
                })
                await writer.drain()
                return

            # Parse data: POST → JSON body, GET → query params
            if method == "POST":
                try:
                    data = json.loads(body) if body else {}
                except json.JSONDecodeError as exc:
                    self._write_response(
                        writer, 400, {"ok": False, "error": f"invalid JSON: {exc}"},
                    )
                    await writer.drain()
                    return
            else:
                data = query

            # Execute handler
            result = await handler(self.bot, data)
            self._write_response(writer, 200, result or {"ok": True})
            await writer.drain()

        except Exception:
            logger.exception("Request handling error")
            try:
                self._write_response(writer, 500, {"ok": False, "error": "internal server error"})
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    # ── start / stop / run ────────────────────────────────────────────

    async def start(self) -> None:
        """Start the server (async).

        If routers were added via :meth:`include_router`, also starts
        VK Teams long-polling in the same event loop.

        Registers SIGINT/SIGTERM handlers for graceful shutdown.

        Use inside an existing loop::

            asyncio.create_task(server.start())
        """
        self._running = True
        self._shutdown_event.clear()

        srv = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
        )

        tasks: list[asyncio.Task[None]] = []
        try:
            await self._emit_startup()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, self._stop_signal)

            addrs = ", ".join(str(s.getsockname()) for s in srv.sockets)
            routes = ", ".join(sorted(self._routes)) or "(none)"
            logger.info("BotServer listening on %s", addrs)
            logger.info("Routes: %s + /health", routes)

            tasks.append(asyncio.create_task(srv.serve_forever()))

            async def _shutdown_waiter() -> None:
                await self._shutdown_event.wait()

            tasks.append(asyncio.create_task(_shutdown_waiter()))

            if self._dispatcher:
                self._dispatcher._running = True
                tasks.append(asyncio.create_task(self._dispatcher._polling(self.bot)))
                logger.info("Polling enabled — bot handlers will receive VK Teams events")

            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            logger.info("Server cancelled")
        finally:
            self._running = False
            for t in tasks:
                if not t.done():
                    t.cancel()
            srv.close()
            await srv.wait_closed()
            await self._emit_shutdown()
            await self.bot.close()

    def stop(self) -> None:
        """Stop the server gracefully.

        Stops the HTTP server and VK Teams polling (if enabled).
        """
        self._running = False
        if self._dispatcher:
            self._dispatcher._running = False
        self._shutdown_event.set()

    def _stop_signal(self) -> None:
        logger.info("Received stop signal")
        self.stop()

    def run(self, host: str | None = None, port: int | None = None) -> None:
        """Start the server (blocking).

        Convenience wrapper around ``asyncio.run(server.start())``.
        """
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        asyncio.run(self.start())
