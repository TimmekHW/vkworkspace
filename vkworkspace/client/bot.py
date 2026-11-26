from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import os
import random
import re
import ssl
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, BinaryIO, Self
from urllib.parse import urlsplit

import httpx2
from pydantic import ValidationError

from vkworkspace.client.ssl_utils import (
    friendly_ssl_hint,
    is_mincifry_alias,
    normalize_verify,
    resolve_mincifry,
)
from vkworkspace.enums import ParseMode
from vkworkspace.exceptions import (
    FileDownloadError,
    SSLVerificationError,
    VKTeamsAPIError,
    VKTeamsHTTPError,
    VKTeamsNetworkError,
)
from vkworkspace.types.chat import ChatInfo
from vkworkspace.types.event import Update
from vkworkspace.types.file import File
from vkworkspace.types.input_file import InputFile, _filename_from_url
from vkworkspace.types.message import ParentMessage
from vkworkspace.types.response import APIResponse
from vkworkspace.types.thread import Thread, ThreadSubscribers
from vkworkspace.types.user import BotInfo, ChatMember, User, UserInfo

logger = logging.getLogger(__name__)

_UNSET: Any = object()  # sentinel: "caller didn't pass parse_mode"

_CONNECT_TIMEOUT = 10.0
_POOL_TIMEOUT = 10.0
_MAX_CONNECTIONS = 100
_POLL_MAX_CONNECTIONS = 4
_DEADLINE_SLACK = 5.0

# The request never left the client: repeating it cannot duplicate anything.
_NOT_SENT_ERRORS = (
    httpx2.ConnectError,
    httpx2.ConnectTimeout,
    httpx2.PoolTimeout,
    httpx2.ProxyError,
)
# The request may have reached the server: the outcome is unknown.
_OUTCOME_UNKNOWN_ERRORS = (
    httpx2.ReadTimeout,
    httpx2.WriteTimeout,
    httpx2.ReadError,
    httpx2.WriteError,
    httpx2.RemoteProtocolError,
)
# Methods that create something new on every call. They are not repeated when
# the outcome of the previous attempt is unknown.
_NON_REPEATABLE = frozenset(
    {
        "messages/sendText",
        "messages/sendTextWithDeeplink",
        "messages/sendFile",
        "messages/sendVoice",
        "chats/createChat",
        "threads/add",
    }
)


class _ClientState:
    """Bookkeeping for an ``httpx2.AsyncClient`` created by :class:`Bot`."""

    __slots__ = ("connect_failures", "in_flight", "limit", "retired")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.in_flight = 0
        self.connect_failures = 0
        self.retired = False


def _files_repeatable(files: dict[str, Any]) -> bool:
    """True if every file object can be read again for a repeated upload."""
    for value in files.values():
        fp = value[1] if isinstance(value, tuple) else value
        if isinstance(fp, (bytes, str)):
            continue
        try:
            if not fp.seekable():
                return False
        except (AttributeError, ValueError):
            return False
    return True


#: ``await make_request(endpoint, params, files)`` → the decoded JSON answer.
MakeRequest = Callable[
    [str, dict[str, Any] | None, dict[str, Any] | None], Awaitable[dict[str, Any]]
]
#: ``async def middleware(make_request, endpoint, params, files)``.
RequestMiddleware = Callable[
    [MakeRequest, str, dict[str, Any] | None, dict[str, Any] | None],
    Awaitable[dict[str, Any]],
]

_MARKDOWN_ESCAPE = re.compile(r"\\(.)", re.DOTALL)


def _is_format_error(exc: VKTeamsAPIError) -> bool:
    return exc.message.startswith("Format error")


def _format_repairs(params: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Variants of a message rejected with «Format error», most faithful first."""
    field = "text" if "text" in params else "caption" if "caption" in params else None
    if field is None or not isinstance(params[field], str):
        return
    text: str = params[field]
    mode = str(params.get("parseMode") or "").lower()
    plain = text
    if mode == "html":
        from vkworkspace.formatting import from_html

        try:
            tree = from_html(text)
            repaired, plain = tree.as_html(), tree.as_plain()
        except Exception:  # the fallback must not replace the server's error with its own
            logger.debug("from_html failed on a rejected message", exc_info=True)
            return
        if repaired and repaired != text:
            yield "with repaired HTML", {**params, field: repaired}
    elif mode == "markdownv2":
        plain = _MARKDOWN_ESCAPE.sub(r"\1", text)
    if not plain:
        return
    without = {k: v for k, v in params.items() if k not in ("parseMode", "format")}
    without[field] = plain
    if without != params:
        yield "as plain text", without


def _jittered(delay: float) -> float:
    """*delay* shortened by a random part of up to a half.

    Many bots that lost the same server do not come back in the same instant.
    """
    return delay * random.uniform(0.5, 1.0)  # noqa: S311


def _describe(exc: BaseException) -> str:
    """``TypeName: message`` — httpx2 timeouts often carry an empty message."""
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _is_ssl_verification_error(exc: BaseException) -> bool:
    """True if *exc* (or its cause chain) is a TLS cert‑verification failure."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLCertVerificationError):
            return True
        if isinstance(cur, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(cur):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


class RateLimiter:
    """Token-bucket rate limiter.

    Allows short bursts up to ``burst`` requests, then throttles to
    ``rate`` requests per second.  Thread-safe via asyncio lock.

    Args:
        rate: Sustained request rate in requests/second (e.g. ``1.0``).
        burst: Maximum tokens in the bucket (default ``5``).
            Allows up to ``burst`` back-to-back requests before throttling.

    Usage::

        limiter = RateLimiter(rate=1.0, burst=5)
        await limiter.acquire()   # blocks only when bucket is empty
    """

    def __init__(self, rate: float, burst: int = 5) -> None:
        self.rate = rate
        self.burst = burst
        self._tokens: float = float(burst)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Refill tokens proportional to elapsed time
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
            else:
                # Wait until one token becomes available
                wait = (1.0 - self._tokens) / self.rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last_refill = time.monotonic()


class Bot:
    """
    VK Teams Bot API client.

    All methods are async and use httpx2.AsyncClient under the hood.
    Supports ``async with`` for automatic session cleanup.

    Usage::

        bot = Bot(token="YOUR_TOKEN", api_url="https://myteam.mail.ru/bot/v1")
        me = await bot.get_me()

        # Rate-limited bot: max 5 requests per second
        bot = Bot(token="TOKEN", rate_limit=5)

        # Strict: max 1 request per second
        bot = Bot(token="TOKEN", rate_limit=1)

        # Proxy: route API requests through corporate proxy
        bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1",
                  proxy="http://proxy-server:8535")
        # Only Bot API requests go through the proxy.
        # Your other HTTP clients (e.g. requests to 83.166.254.26:8000) are NOT affected.

    Context manager (recommended for FastAPI / background tasks)::

        async with Bot(token="TOKEN", api_url="...") as bot:
            await bot.send_text("user@corp.ru", "Hello!")
        # bot.close() called automatically
    """

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.icq.net/bot/v1",
        timeout: float = 30.0,
        poll_time: int = 60,
        rate_limit: float | None = None,
        proxy: str | None = None,
        parse_mode: ParseMode | str | None = None,
        retry_on_5xx: int | None = 3,
        verify_ssl: bool | str | Path | ssl.SSLContext = True,
        mincifry: bool | None = None,
        format_fallback: bool = True,
    ) -> None:
        """
        Args:
            token: Bot token from BotFather.
            api_url: Base API URL (e.g. ``"https://myteam.mail.ru/bot/v1"``
                for on-premise VK Teams).
            timeout: Seconds to wait for the server's answer (default 30).
                Any call without a file is abandoned ``timeout + 25`` seconds
                after it started (a long-poll: ``poll_time + timeout + 25``).
            poll_time: Long-poll timeout in seconds (default 60).
            rate_limit: Max requests per second. ``None`` = unlimited.
            proxy: HTTP proxy URL (e.g. ``"http://proxy:8535"``).
                Only affects Bot API requests. If omitted, the ``VKT_PROXY``
                environment variable is used when set.
            parse_mode: Default parse mode for all messages
                (``"HTML"`` / ``"MarkdownV2"`` / ``None``).
            retry_on_5xx: Retry count on 5xx and network errors. ``3`` = up
                to 3 retries with exponential backoff. ``None`` or ``0`` = no
                retries. A request that was not sent (connection, proxy and
                pool errors) is always repeated; one with an unknown outcome
                (read timeout, dropped connection) is repeated for every
                method except those that create something new on each call
                (``sendText``, ``sendFile``, ``sendVoice``, ``createChat``,
                ``threads/add``).
            verify_ssl: TLS trust for the server certificate. Accepts:

                * ``True`` (default) — trust what the machine trusts: the
                  Windows store, the system bundle of a Linux image, a bundle
                  mounted into a pod — the certificates are searched for
                  (plus the vendored Минцифры root when *mincifry* is on);
                * ``"mincifry"`` — same as ``True`` with Минцифры trust on;
                * ``False`` — **disable** verification (last resort);
                * a PEM CA‑bundle **path** (``str`` / :class:`~pathlib.Path`) —
                  trust that extra CA **on top of** the defaults, e.g. a
                  private corporate CA;
                * a ready :class:`ssl.SSLContext` from
                  :func:`~vkworkspace.client.ssl_utils.make_ssl_context`.
            mincifry: Trust the **Минцифры** root CA shipped with the package
                (Russian Trusted Root CA) — for machines that do not have it
                installed.
                ``None`` = the ``VKT_MINCIFRY`` environment variable, else the
                build default (:data:`~vkworkspace.client.ssl_utils.MINCIFRY_DEFAULT`).
            format_fallback: When the server rejects a message with
                «Format error», resend it: HTML is rebuilt by
                :func:`vkworkspace.formatting.from_html` (unclosed tags, stray
                ``<`` and ``&``, nesting the server does not render), and if
                that is rejected too, the text goes without markup. A warning
                is logged. ``False`` = raise :class:`VKTeamsAPIError` at once.
        """
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.poll_time = poll_time
        self.rate_limit = rate_limit
        self.proxy = proxy if proxy is not None else (os.environ.get("VKT_PROXY") or None)
        self.parse_mode = parse_mode
        self.retry_on_5xx = retry_on_5xx
        # Keep the raw value for introspection; hand httpx2 a normalized one
        # (SSLContext or bool) — a bare path string is deprecated in httpx2.
        self.verify_ssl = verify_ssl
        self.mincifry = resolve_mincifry(mincifry) or is_mincifry_alias(verify_ssl)
        self._verify = normalize_verify(verify_ssl, mincifry=self.mincifry)
        self.format_fallback = format_fallback
        self.request_middlewares: list[RequestMiddleware] = []
        self._rate_limiter: RateLimiter | None = RateLimiter(rate_limit) if rate_limit else None
        self._session: httpx2.AsyncClient | None = None
        self._poll_session: httpx2.AsyncClient | None = None
        self._clients: dict[httpx2.AsyncClient, _ClientState] = {}
        self._last_event_id: int = 0
        self._user_cache: dict[str, UserInfo] = {}

    # Seconds on top of the read budget after which a call is abandoned no
    # matter what the transport is doing: pool wait + connect + slack.
    DEADLINE_MARGIN = _POOL_TIMEOUT + _CONNECT_TIMEOUT + _DEADLINE_SLACK

    def _new_client(self, max_connections: int = _MAX_CONNECTIONS) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(
            timeout=httpx2.Timeout(
                self.timeout,
                connect=_CONNECT_TIMEOUT,
                pool=_POOL_TIMEOUT,
            ),
            limits=httpx2.Limits(
                max_connections=max_connections,
                max_keepalive_connections=min(20, max_connections),
            ),
            follow_redirects=True,
            proxy=self.proxy,
            verify=self._verify,
        )
        self._clients[client] = _ClientState(limit=max_connections)
        return client

    async def get_session(self) -> httpx2.AsyncClient:
        """The HTTP client behind Bot API calls.

        Ask for it each time it is needed: the bot replaces the client when
        its connection pool is stuck and closes the old one.
        """
        if self._session is None or self._session.is_closed:
            if self._session is not None:
                self._clients.pop(self._session, None)
            self._session = self._new_client()
        return self._session

    async def _get_poll_session(self) -> httpx2.AsyncClient:
        """The HTTP client of the ``events/get`` long-poll.

        It has a connection pool of its own: sends that hang on the server and
        fill the main pool do not keep the long-poll waiting for a connection.
        A client assigned to ``bot._session`` from outside serves the long-poll too.
        """
        session = self._session
        if session is not None and not session.is_closed and session not in self._clients:
            return session
        if self._poll_session is None or self._poll_session.is_closed:
            if self._poll_session is not None:
                self._clients.pop(self._poll_session, None)
            self._poll_session = self._new_client(_POLL_MAX_CONNECTIONS)
        return self._poll_session

    def _retire(
        self, client: httpx2.AsyncClient, reason: str, level: int = logging.WARNING
    ) -> None:
        """Stop using *client* for new requests; it is closed once idle."""
        state = self._clients.get(client)
        if state is None or state.retired:
            return
        state.retired = True
        if self._session is client:
            self._session = None
        if self._poll_session is client:
            self._poll_session = None
        logger.log(level, "Replacing the HTTP connection pool: %s", reason)

    async def _close_client(self, client: httpx2.AsyncClient) -> None:
        self._clients.pop(client, None)
        with contextlib.suppress(Exception):
            await client.aclose()

    @contextlib.asynccontextmanager
    async def _tracked(self, client: httpx2.AsyncClient) -> AsyncGenerator[None, None]:
        """Count a request on *client* and replace the client when its pool is stuck.

        Two signs of a stuck pool:

        * ``PoolTimeout`` while fewer requests are in flight than the pool has
          slots — the slots are held by connections that serve no request;
        * many failed connection attempts since the pool was created — behind
          an HTTP proxy each failed TLS handshake leaves a connection that the
          pool never frees. The pool is replaced before they fill it.
        """
        state = self._clients.get(client)
        if state is None:
            yield
            return
        state.in_flight += 1
        try:
            yield
        except httpx2.PoolTimeout:
            if state.in_flight <= state.limit:
                self._retire(
                    client,
                    f"no free connection with {state.in_flight} request(s) in flight "
                    f"and a limit of {state.limit}",
                )
            raise
        except (httpx2.ConnectError, httpx2.ConnectTimeout):
            state.connect_failures += 1
            if state.connect_failures >= max(1, state.limit // 2):
                self._retire(
                    client,
                    f"{state.connect_failures} failed connection attempts since it was created",
                    logging.INFO,
                )
            raise
        finally:
            state.in_flight -= 1
            if state.retired and state.in_flight == 0:
                await self._close_client(client)

    async def close(self) -> None:
        for client in list(self._clients):
            await self._close_client(client)
        if self._session and not self._session.is_closed:
            await self._session.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ── internal helpers ──────────────────────────────────────────────

    def _params(self, **kwargs: Any) -> dict[str, Any]:
        params: dict[str, Any] = {"token": self.token}
        for key, value in kwargs.items():
            if value is None:
                continue
            if isinstance(value, bool):
                params[key] = "true" if value else "false"
            elif isinstance(value, (list, dict)):
                params[key] = json.dumps(value, ensure_ascii=False)
            else:
                params[key] = value
        return params

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a Bot API method through :attr:`request_middlewares`."""
        call: MakeRequest = self._send
        for middleware in reversed(self.request_middlewares):
            call = functools.partial(middleware, call)
        return await call(endpoint, params, files)

    def request_middleware(self, middleware: RequestMiddleware) -> RequestMiddleware:
        """Register a middleware around every Bot API call (usable as a decorator).

        The middleware sees one logical call: built-in retries and the format
        fallback happen inside ``make_request``::

            @bot.request_middleware
            async def timing(make_request, endpoint, params, files):
                started = time.monotonic()
                try:
                    return await make_request(endpoint, params, files)
                finally:
                    metrics.observe(endpoint, time.monotonic() - started)

        ``params`` holds the bot token under ``"token"``.
        """
        self.request_middlewares.append(middleware)
        return middleware

    async def _send(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The call itself: retries, format fallback, library exception types."""
        try:
            return await self._send_repairing_format(endpoint, params, files)
        except httpx2.HTTPStatusError as exc:
            raise VKTeamsHTTPError(endpoint, exc.response.status_code, exc) from exc
        except httpx2.HTTPError as exc:
            raise VKTeamsNetworkError(endpoint, _describe(exc), exc) from exc

    async def _send_repairing_format(
        self,
        endpoint: str,
        params: dict[str, Any] | None,
        files: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Resend a message the server rejected with «Format error».

        First with the markup rebuilt by :func:`vkworkspace.formatting.from_html`
        (HTML only), then as plain text.
        """
        try:
            return await self._send_with_retries(endpoint, params, files)
        except VKTeamsAPIError as exc:
            if not (self.format_fallback and params and _is_format_error(exc)):
                raise
            if files and not _files_repeatable(files):
                raise
            for how, repaired in _format_repairs(params):
                try:
                    data = await self._send_with_retries(endpoint, repaired, files)
                except VKTeamsAPIError as again:
                    if _is_format_error(again):
                        continue
                    raise
                logger.warning(
                    "«Format error» from %s: the message was sent %s. Text: %.300r",
                    endpoint,
                    how,
                    params.get("text", params.get("caption")),
                )
                return data
            raise

    async def _send_with_retries(
        self,
        endpoint: str,
        params: dict[str, Any] | None,
        files: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if self._rate_limiter:
            await self._rate_limiter.acquire()

        url = f"{self.api_url}/{endpoint}"

        max_attempts = (self.retry_on_5xx or 0) + 1
        if files and not _files_repeatable(files):
            max_attempts = 1

        t0 = time.monotonic()
        # An upload takes as long as the file needs. Any other call, with all
        # its retries, ends within the read budget plus DEADLINE_MARGIN.
        give_up_at = (
            None if files else t0 + self._read_budget(endpoint, params) + self.DEADLINE_MARGIN
        )
        logger.debug("→ %s", endpoint)

        for attempt in range(max_attempts):
            try:
                data = await self._call(endpoint, url, params, files, give_up_at)
            except Exception as exc:
                if not self._is_retryable(endpoint, exc):
                    raise
                if attempt >= max_attempts - 1:
                    if isinstance(exc, VKTeamsAPIError):
                        logger.error(
                            "Server error from %s persisted after %d attempts: %s (params: %s)",
                            endpoint,
                            max_attempts,
                            exc.message,
                            {k: v for k, v in (params or {}).items() if k != "token"},
                        )
                    raise
                delay = _jittered(min(2**attempt, 8))
                if give_up_at is not None and time.monotonic() + delay >= give_up_at:
                    raise  # no time left for another attempt
                logger.warning(
                    "%s from %s (attempt %d/%d), retrying in %.1fs...",
                    self._failure_label(exc),
                    endpoint,
                    attempt + 1,
                    max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.debug("← %s (%.3fs)", endpoint, time.monotonic() - t0)
                return data

        raise RuntimeError("unreachable")  # pragma: no cover - loop returns or raises

    async def _call(
        self,
        endpoint: str,
        url: str,
        params: dict[str, Any] | None,
        files: dict[str, Any] | None,
        give_up_at: float | None,
    ) -> dict[str, Any]:
        """One HTTP exchange with the Bot API. Raises on any failure."""
        if endpoint == "events/get":
            session = await self._get_poll_session()
        else:
            session = await self.get_session()
        try:
            async with self._tracked(session):
                resp = await self._post(session, endpoint, url, params, files, give_up_at)
        except httpx2.ConnectError as exc:
            if _is_ssl_verification_error(exc):
                host = urlsplit(self.api_url).hostname
                raise SSLVerificationError(friendly_ssl_hint(host, mincifry=self.mincifry)) from exc
            raise

        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            # A page of a proxy or a gateway instead of the Bot API.
            raise VKTeamsNetworkError(
                endpoint,
                f"the answer is not Bot API JSON (HTTP {resp.status_code}, "
                f"{resp.headers.get('content-type', 'no content type')}): {resp.text[:200]!r}",
            )
        if data.get("ok") is False:
            raise VKTeamsAPIError(method=endpoint, message=data.get("description", "Unknown error"))
        return data

    async def _post(
        self,
        session: httpx2.AsyncClient,
        endpoint: str,
        url: str,
        params: dict[str, Any] | None,
        files: dict[str, Any] | None,
        give_up_at: float | None,
    ) -> httpx2.Response:
        """POST that is abandoned at *give_up_at* (``None`` = never: an upload).

        httpx2 timeouts limit each phase (pool, connect, write, one read), not
        the call. The call, with its retries, has a deadline of its own: the
        read budget plus :attr:`DEADLINE_MARGIN`.
        """
        if give_up_at is None:
            return await session.post(url, data=params, files=files)

        kwargs: dict[str, Any] = {}
        budget = self._read_budget(endpoint, params)
        if endpoint == "events/get":
            kwargs["timeout"] = httpx2.Timeout(budget, connect=_CONNECT_TIMEOUT, pool=_POOL_TIMEOUT)
        deadline = budget + self.DEADLINE_MARGIN
        left = give_up_at - time.monotonic()
        try:
            return await asyncio.wait_for(session.post(url, data=params, **kwargs), max(left, 0.0))
        except TimeoutError:
            # The attempt had time for every httpx2 timeout to fire and none
            # did: the pool is stuck. A retry cut short by the deadline says nothing.
            if left >= deadline - _DEADLINE_SLACK:
                self._retire(session, f"{endpoint} exceeded its {deadline:.0f}s deadline")
            raise httpx2.ReadTimeout(f"{endpoint} got no response within {deadline:.0f}s") from None

    def _read_budget(self, endpoint: str, params: dict[str, Any] | None) -> float:
        """Seconds the server may take to answer; the long-poll adds ``pollTime``."""
        budget = float(self.timeout)
        if endpoint == "events/get":
            try:
                budget += float((params or {}).get("pollTime", self.poll_time))
            except (TypeError, ValueError):
                budget += float(self.poll_time)
        return budget

    @staticmethod
    def _is_retryable(endpoint: str, exc: BaseException) -> bool:
        """Whether a failed attempt may be repeated.

        * the request was not sent (connect / proxy / pool errors) — always;
        * HTTP 5xx other than 504 and ``"Server error"`` — always;
        * the outcome is unknown (read timeout, dropped connection, HTTP 504 —
          the gateway stopped waiting for the server, ``"Request timed out"``)
          — unless the method creates something new on every call
          (see ``_NON_REPEATABLE``).
        """
        if isinstance(exc, _NOT_SENT_ERRORS):
            return True
        if isinstance(exc, httpx2.HTTPStatusError):
            status = exc.response.status_code
            if status == 504:
                return endpoint not in _NON_REPEATABLE
            return status >= 500
        if isinstance(exc, VKTeamsAPIError):
            if exc.message.startswith("Server error"):
                return True
            return exc.message.startswith("Request timed out") and endpoint not in _NON_REPEATABLE
        if isinstance(exc, _OUTCOME_UNKNOWN_ERRORS):
            return endpoint not in _NON_REPEATABLE
        return False

    @staticmethod
    def _failure_label(exc: BaseException) -> str:
        if isinstance(exc, httpx2.HTTPStatusError):
            return f"HTTP {exc.response.status_code}"
        if isinstance(exc, VKTeamsAPIError):
            return f"«{exc.message}»"
        return _describe(exc)

    def _resolve_parse_mode(self, parse_mode: Any) -> str | None:
        """Return explicit value or fall back to ``self.parse_mode``."""
        if parse_mode is _UNSET:
            return self.parse_mode
        return str(parse_mode) if parse_mode is not None else None

    @staticmethod
    def _keyboard_json(keyboard: Any) -> str | None:
        if keyboard is None:
            return None
        if isinstance(keyboard, str):
            return keyboard
        if isinstance(keyboard, list):
            return json.dumps(keyboard, ensure_ascii=False)
        if hasattr(keyboard, "as_json"):
            result: str = keyboard.as_json()
            return result
        return None

    @staticmethod
    def _parent_topic_json(parent_topic: ParentMessage | dict[str, Any] | None) -> str | None:
        if parent_topic is None:
            return None
        if isinstance(parent_topic, ParentMessage):
            return json.dumps(
                {
                    "chatId": parent_topic.chat_id,
                    "messageId": parent_topic.message_id,
                    "type": parent_topic.type,
                },
                ensure_ascii=False,
            )
        if isinstance(parent_topic, dict):
            return json.dumps(parent_topic, ensure_ascii=False)
        return None

    @staticmethod
    def _format_json(format_: Any) -> str | None:
        if format_ is None:
            return None
        if isinstance(format_, str):
            return format_
        if isinstance(format_, dict):
            return json.dumps(format_, ensure_ascii=False)
        if hasattr(format_, "to_json"):
            result: str = format_.to_json()
            return result
        return None

    @staticmethod
    def _msg_ids(value: str | list[str] | None) -> str | None:
        """Normalize message ID(s) to a comma-separated string.

        The API expects ``replyMsgId`` / ``forwardMsgId`` as a plain
        string (single ID) or comma-separated IDs — **not** a JSON array.
        """
        if value is None:
            return None
        if isinstance(value, list):
            return ",".join(value)
        return value

    def _file_payload(
        self,
        file: InputFile | BinaryIO | None,
    ) -> dict[str, Any] | None:
        if file is None:
            return None
        if isinstance(file, InputFile):
            filename, fp = file.read()
            return {"file": (filename, fp)}
        return {"file": file}

    async def _upload(
        self,
        endpoint: str,
        params: dict[str, Any],
        file: InputFile | BinaryIO | None,
    ) -> dict[str, Any]:
        """Call *endpoint* with an optional file; a file opened here is closed afterwards."""
        files = self._file_payload(file)
        try:
            return await self._request(endpoint, params, files)
        finally:
            if files and isinstance(file, InputFile) and isinstance(file.file, (str, Path)):
                files["file"][1].close()

    # ── Bot Info ──────────────────────────────────────────────────────

    async def get_me(self) -> BotInfo:
        """Get bot's own info. ``self/get``"""
        data = await self._request("self/get", self._params())
        return BotInfo.model_validate(data)

    # ── Events / Polling ──────────────────────────────────────────────

    async def get_events(
        self,
        last_event_id: int | None = None,
        poll_time: int | None = None,
    ) -> list[Update]:
        """Long-poll for events. ``events/get``

        Raises like every other call when the server does not answer or answers
        with an HTTP error. ``Dispatcher.start_polling`` logs the failure and
        polls again after a pause.
        """
        eid = last_event_id if last_event_id is not None else self._last_event_id
        pt = poll_time if poll_time is not None else self.poll_time

        data = await self._request(
            "events/get",
            self._params(pollTime=pt, lastEventId=eid),
        )

        events: list[Update] = []
        skipped = 0
        for raw in data.get("events", []):
            try:
                update = Update.model_validate(raw)
            except ValidationError as exc:
                # One event the library cannot read must not hold back the rest:
                # without moving past it the server returns the same batch forever.
                skipped += 1
                event_id = raw.get("eventId") if isinstance(raw, dict) else None
                logger.error(
                    "Event %s skipped — it does not match the Bot API format (%s). Raw: %.500r",
                    event_id,
                    "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()),
                    raw,
                )
                if isinstance(event_id, int) and event_id > self._last_event_id:
                    self._last_event_id = event_id
                continue
            events.append(update)
            self._last_event_id = max(self._last_event_id, update.event_id)

        if skipped and not events and self._last_event_id == eid:
            # Nothing to move past (the event carries no usable id): do not spin.
            await asyncio.sleep(1.0)
        return events

    # ── Messages ──────────────────────────────────────────────────────

    TEXT_LENGTH_WARNING = 4096

    async def send_text(
        self,
        chat_id: str,
        text: str,
        reply_msg_id: str | list[str] | None = None,
        forward_chat_id: str | None = None,
        forward_msg_id: str | list[str] | None = None,
        inline_keyboard_markup: Any = None,
        parse_mode: ParseMode | str | None = _UNSET,
        format_: dict[str, Any] | Any | None = None,
        parent_topic: ParentMessage | dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> APIResponse:
        """Send a text message. ``messages/sendText``

        Args:
            chat_id: Target chat ID (email-like, e.g. ``"user@company.ru"``).
            text: Message text (max ~4096 chars recommended).
            reply_msg_id: Message ID(s) to reply to.
            forward_chat_id: Chat to forward from.
            forward_msg_id: Message ID(s) to forward.
            inline_keyboard_markup: Inline keyboard
                (``InlineKeyboardBuilder.as_markup()`` or raw JSON).
            parse_mode: ``"HTML"`` / ``"MarkdownV2"`` / ``None``.
                Defaults to ``bot.parse_mode``.
            format_: Offset/length formatting (``FormatBuilder`` or raw dict).
            parent_topic: Send inside a thread.
            request_id: Idempotency key — prevents duplicate messages.

        Returns:
            APIResponse with ``msg_id`` and ``ok`` status.

        Example::

            await bot.send_text("user@corp.ru", "Hello!")

            # With keyboard
            builder = InlineKeyboardBuilder()
            builder.button(text="OK", callback_data="ok")
            await bot.send_text(chat_id, "Choose:", inline_keyboard_markup=builder.as_markup())
        """
        if len(text) > self.TEXT_LENGTH_WARNING:
            logger.warning(
                "Text length %d exceeds %d chars — may cause UI lag or be rejected by the server",
                len(text),
                self.TEXT_LENGTH_WARNING,
            )
        data = await self._request(
            "messages/sendText",
            self._params(
                chatId=chat_id,
                text=text,
                replyMsgId=self._msg_ids(reply_msg_id),
                forwardChatId=forward_chat_id,
                forwardMsgId=self._msg_ids(forward_msg_id),
                inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
                parseMode=self._resolve_parse_mode(parse_mode),
                format=self._format_json(format_),
                parent_topic=self._parent_topic_json(parent_topic),
                requestId=request_id,
            ),
        )
        return APIResponse.model_validate(data)

    async def send_text_with_deeplink(
        self,
        chat_id: str,
        text: str,
        deeplink: str,
        inline_keyboard_markup: Any = None,
        parse_mode: ParseMode | str | None = _UNSET,
        format_: dict[str, Any] | Any | None = None,
    ) -> APIResponse:
        """Send text with deeplink. ``messages/sendTextWithDeeplink``

        *deeplink* is an identifier passed to the bot when a user taps
        the deeplink button — useful for mini-app or bot-start scenarios.
        """
        data = await self._request(
            "messages/sendTextWithDeeplink",
            self._params(
                chatId=chat_id,
                text=text,
                deeplink=deeplink,
                inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
                parseMode=self._resolve_parse_mode(parse_mode),
                format=self._format_json(format_),
            ),
        )
        return APIResponse.model_validate(data)

    async def edit_text(
        self,
        chat_id: str,
        msg_id: str,
        text: str,
        inline_keyboard_markup: Any = None,
        parse_mode: ParseMode | str | None = _UNSET,
        format_: dict[str, Any] | Any | None = None,
    ) -> APIResponse:
        """Edit message text. ``messages/editText``"""
        if len(text) > self.TEXT_LENGTH_WARNING:
            logger.warning(
                "Text length %d exceeds %d chars — may cause UI lag or be rejected by the server",
                len(text),
                self.TEXT_LENGTH_WARNING,
            )
        data = await self._request(
            "messages/editText",
            self._params(
                chatId=chat_id,
                msgId=msg_id,
                text=text,
                inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
                parseMode=self._resolve_parse_mode(parse_mode),
                format=self._format_json(format_),
            ),
        )
        return APIResponse.model_validate(data)

    async def delete_messages(
        self,
        chat_id: str,
        msg_id: str,
    ) -> APIResponse:
        """Delete messages. ``messages/deleteMessages``"""
        data = await self._request(
            "messages/deleteMessages",
            self._params(chatId=chat_id, msgId=msg_id),
        )
        return APIResponse.model_validate(data)

    async def send_file(
        self,
        chat_id: str,
        file_id: str | None = None,
        file: InputFile | BinaryIO | None = None,
        caption: str | None = None,
        reply_msg_id: str | list[str] | None = None,
        forward_chat_id: str | None = None,
        forward_msg_id: str | list[str] | None = None,
        inline_keyboard_markup: Any = None,
        parse_mode: ParseMode | str | None = _UNSET,
        format_: dict[str, Any] | Any | None = None,
        parent_topic: ParentMessage | dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> APIResponse:
        """Send a file or image. ``messages/sendFile``

        Images (JPG/PNG/WEBP/GIF) are displayed inline as photos.
        Other files appear as document attachments.

        Provide either *file* (upload) or *file_id* (resend existing).

        Args:
            chat_id: Target chat ID.
            file_id: ID of a previously uploaded file (no re-upload needed).
            file: File to upload — ``InputFile``, or open ``BinaryIO``.
            caption: Text caption shown below the file.
            reply_msg_id: Message ID(s) to reply to.
            forward_chat_id: Chat to forward from.
            forward_msg_id: Message ID(s) to forward.
            inline_keyboard_markup: Inline keyboard.
            parse_mode: Parse mode for caption.
            format_: Offset/length formatting for caption.
            parent_topic: Send inside a thread.
            request_id: Idempotency key.

        Returns:
            APIResponse with ``msg_id``, ``file_id``, ``ok``.

        Example::

            # Upload from disk
            await bot.send_file(chat_id, file=InputFile("report.pdf"))

            # Photo from URL
            photo = await InputFile.from_url("https://http.cat/200.jpg")
            await bot.send_file(chat_id, file=photo, caption="OK cat")

            # Resend by file_id (instant, no re-upload)
            await bot.send_file(chat_id, file_id="abc123")
        """
        params = self._params(
            chatId=chat_id,
            fileId=file_id,
            caption=caption,
            replyMsgId=self._msg_ids(reply_msg_id),
            forwardChatId=forward_chat_id,
            forwardMsgId=self._msg_ids(forward_msg_id),
            inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
            parseMode=self._resolve_parse_mode(parse_mode),
            format=self._format_json(format_),
            parent_topic=self._parent_topic_json(parent_topic),
            requestId=request_id,
        )
        data = await self._upload("messages/sendFile", params, file)
        return APIResponse.model_validate(data)

    async def send_voice(
        self,
        chat_id: str,
        file_id: str | None = None,
        file: InputFile | BinaryIO | None = None,
        reply_msg_id: str | list[str] | None = None,
        forward_chat_id: str | None = None,
        forward_msg_id: str | list[str] | None = None,
        inline_keyboard_markup: Any = None,
        parent_topic: ParentMessage | dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> APIResponse:
        """Send a voice message. ``messages/sendVoice``

        The recommended format is **OGG/Opus**. Use
        ``vkworkspace.utils.voice.convert_to_ogg_opus()`` to convert
        from MP3/WAV/FLAC (requires ``pip install av``).

        Args:
            chat_id: Target chat ID.
            file_id: ID of a previously uploaded voice (no re-upload).
            file: Voice file — ``InputFile`` with OGG/Opus data.
            reply_msg_id: Message ID(s) to reply to.
            forward_chat_id: Chat to forward from.
            forward_msg_id: Message ID(s) to forward.
            inline_keyboard_markup: Inline keyboard.
            parent_topic: Send inside a thread.
            request_id: Idempotency key.

        Returns:
            APIResponse with ``msg_id``, ``file_id``, ``ok``.

        Example::

            from vkworkspace.utils.voice import convert_to_ogg_opus

            ogg = convert_to_ogg_opus("recording.mp3")
            await bot.send_voice(chat_id, file=InputFile(ogg, filename="voice.ogg"))
        """
        params = self._params(
            chatId=chat_id,
            fileId=file_id,
            replyMsgId=self._msg_ids(reply_msg_id),
            forwardChatId=forward_chat_id,
            forwardMsgId=self._msg_ids(forward_msg_id),
            inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
            parent_topic=self._parent_topic_json(parent_topic),
            requestId=request_id,
        )
        data = await self._upload("messages/sendVoice", params, file)
        return APIResponse.model_validate(data)

    async def answer_callback_query(
        self,
        query_id: str,
        text: str = "",
        show_alert: bool = False,
        url: str | None = None,
    ) -> APIResponse:
        """Answer a callback query (inline button press).

        Must be called within ~30s of receiving the callback, otherwise
        the user sees a loading spinner.

        Args:
            query_id: ID from ``CallbackQuery.query_id``.
            text: Notification text shown to the user.
            show_alert: Show as a popup alert instead of a toast.
            url: URL to open in the user's browser.

        Example::

            @router.callback_query(F.callback_data == "confirm")
            async def on_confirm(query: CallbackQuery):
                await query.answer("Done!")  # uses this method internally
        """
        data = await self._request(
            "messages/answerCallbackQuery",
            self._params(
                queryId=query_id,
                text=text,
                showAlert=show_alert,
                url=url,
            ),
        )
        return APIResponse.model_validate(data)

    # ── Chat Management ───────────────────────────────────────────────

    async def get_chat_info(self, chat_id: str) -> ChatInfo:
        """Get chat info. ``chats/getInfo``"""
        data = await self._request(
            "chats/getInfo",
            self._params(chatId=chat_id),
        )
        return ChatInfo.model_validate(data)

    # ── Users ─────────────────────────────────────────────────────────

    async def get_user(self, user: str, *, cache: bool = True) -> UserInfo:
        """Resolve a user by ``user_id`` (email) or ``nick``. ``chats/getInfo``

        Gives you the person's name for a ``user_id`` — and the other way
        round, a ``user_id`` / ``mention`` for a nick.

        Args:
            user: ``"ivanov@company.ru"`` (user_id) or ``"ivanov"`` (nick).
            cache: Remember the result for the bot's lifetime (default). Pass
                ``False`` to always hit the API; :meth:`clear_user_cache`
                drops everything remembered.

        Returns:
            :class:`~vkworkspace.types.user.UserInfo` with ``full_name``,
            ``mention``, ``first_name``, ``last_name``, ``nick``, ``is_bot``,
            ``uin``. ``user_id`` is the email when you passed one; for a nick
            lookup it is the numeric ``uin`` from the avatar URL (the ID VK
            Teams uses for bots), or the nick itself if no avatar.

        Raises:
            ValueError: If *user* is a group / channel, not a person.
            VKTeamsAPIError: If the API rejects the lookup.

        Example::

            user = await bot.get_user("ivanov@company.ru")
            await bot.send_text(chat_id, f"{user.mention}, {user.full_name} на связи")

            bot_info = await bot.get_user("the_equalizer_alert_bot")  # by nick
            bot_info.user_id, bot_info.is_bot
        """
        key = user.strip()
        if cache and key in self._user_cache:
            return self._user_cache[key]

        info = await self.get_chat_info(key)
        if info.type in ("group", "channel"):
            raise ValueError(f"{key!r} is a {info.type}, not a user")

        uin = UserInfo.parse_uin(info.photos)
        user_id = key if "@" in key else (uin or key)
        result = UserInfo(
            userId=user_id,
            firstName=info.first_name,
            lastName=info.last_name,
            nick=info.nick,
            about=info.about,
            isBot=info.is_bot,
            uin=uin,
            photos=info.photos,
        )
        if cache:
            self._user_cache[key] = result
            self._user_cache[user_id] = result
        return result

    async def get_user_name(self, user: str, *, cache: bool = True) -> str:
        """``full_name`` of a user by ``user_id`` or nick. Shortcut for :meth:`get_user`.

        Example::

            name = await bot.get_user_name("ivanov@company.ru")   # "Иван Иванов"
        """
        return (await self.get_user(user, cache=cache)).full_name

    def clear_user_cache(self) -> None:
        """Forget everything :meth:`get_user` has cached."""
        self._user_cache.clear()

    async def get_chat_admins(self, chat_id: str) -> list[ChatMember]:
        """Get chat admins. ``chats/getAdmins`` (read-only).

        Returns the list of users with ``admin`` / ``creator`` role in the
        chat. Each :class:`ChatMember` carries ``admin`` / ``creator`` flags.

        .. note::
            Bot API has **no admin-grant counterpart** — there is no
            ``chats/setAdmin``, ``chats/setRole``, ``chats/promote*`` or
            ``chats/grantAdmin`` method. Verified against the canonical
            Swagger spec, ``mail-ru-im/bot-golang`` upstream docs, full git
            history of all official SDKs, Wayback ``api.yaml`` snapshots
            2020–2024, Sourcegraph global code search, and live
            brute-force of ~130 candidate paths against the public
            endpoint (all returned the same ``"Unknown method"`` baseline).

            The only programmatic promotion path is the on-premises
            ``rapi/modChatMember`` call on the **internal** host, which
            requires the server's ``admin_key`` from
            ``/usr/local/etc/import_prismtokens.yaml`` (NOT a bot token).
            Bot-side ACL for private flows is gated by per-feature
            ``stdb`` tables (``bots_can_write_first``,
            ``bots_can_send_deeplink``, …), not a single
            ``bot_api_private_methods`` table.
        """
        data = await self._request(
            "chats/getAdmins",
            self._params(chatId=chat_id),
        )
        return [ChatMember.model_validate(m) for m in data.get("admins", [])]

    async def get_chat_members(
        self,
        chat_id: str,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Get chat members. ``chats/getMembers``"""
        return await self._request(
            "chats/getMembers",
            self._params(chatId=chat_id, cursor=cursor),
        )

    async def get_blocked_users(self, chat_id: str) -> list[User]:
        """Get blocked users. ``chats/getBlockedUsers``"""
        data = await self._request(
            "chats/getBlockedUsers",
            self._params(chatId=chat_id),
        )
        return [User.model_validate(u) for u in data.get("users", [])]

    async def get_pending_users(self, chat_id: str) -> list[User]:
        """Get pending users. ``chats/getPendingUsers``"""
        data = await self._request(
            "chats/getPendingUsers",
            self._params(chatId=chat_id),
        )
        return [User.model_validate(u) for u in data.get("users", [])]

    async def block_user(
        self,
        chat_id: str,
        user_id: str,
        del_last_messages: bool = False,
    ) -> APIResponse:
        """Block user. ``chats/blockUser``"""
        data = await self._request(
            "chats/blockUser",
            self._params(
                chatId=chat_id,
                userId=user_id,
                delLastMessages=del_last_messages,
            ),
        )
        return APIResponse.model_validate(data)

    async def unblock_user(self, chat_id: str, user_id: str) -> APIResponse:
        """Unblock user. ``chats/unblockUser``"""
        data = await self._request(
            "chats/unblockUser",
            self._params(chatId=chat_id, userId=user_id),
        )
        return APIResponse.model_validate(data)

    async def resolve_pending(
        self,
        chat_id: str,
        approve: bool = True,
        user_id: str = "",
        everyone: bool = False,
    ) -> APIResponse:
        """Resolve pending join requests. ``chats/resolvePending``"""
        data = await self._request(
            "chats/resolvePending",
            self._params(
                chatId=chat_id,
                approve=approve,
                userId=user_id or None,
                everyone=everyone,
            ),
        )
        return APIResponse.model_validate(data)

    async def set_chat_title(self, chat_id: str, title: str) -> APIResponse:
        """Set chat title. ``chats/setTitle``"""
        data = await self._request(
            "chats/setTitle",
            self._params(chatId=chat_id, title=title),
        )
        return APIResponse.model_validate(data)

    async def set_chat_about(self, chat_id: str, about: str) -> APIResponse:
        """Set chat description. ``chats/setAbout``"""
        data = await self._request(
            "chats/setAbout",
            self._params(chatId=chat_id, about=about),
        )
        return APIResponse.model_validate(data)

    async def set_chat_rules(self, chat_id: str, rules: str) -> APIResponse:
        """Set chat rules. ``chats/setRules``"""
        data = await self._request(
            "chats/setRules",
            self._params(chatId=chat_id, rules=rules),
        )
        return APIResponse.model_validate(data)

    async def delete_chat_members(
        self,
        chat_id: str,
        members: list[str],
    ) -> APIResponse:
        """Remove members from chat. ``chats/members/delete``"""
        data = await self._request(
            "chats/members/delete",
            self._params(
                chatId=chat_id,
                members=[{"sn": m} for m in members],
            ),
        )
        return APIResponse.model_validate(data)

    async def add_chat_members(
        self,
        chat_id: str,
        members: list[str],
    ) -> APIResponse:
        """Add members to chat. ``chats/members/add``

        .. warning::
           Private (myteam_only) endpoint — disabled by default for new
           bots. If the server returns ``"Method not allowed"``, ask
           your platform admin / integrators to enable
           ``chats/members/add`` for this bot. See :meth:`create_chat`
           for the full ACL explanation.
        """
        data = await self._request(
            "chats/members/add",
            self._params(
                chatId=chat_id,
                members=[{"sn": m} for m in members],
            ),
        )
        return APIResponse.model_validate(data)

    async def create_chat(
        self,
        name: str,
        about: str = "",
        rules: str = "",
        members: list[str] | None = None,
        public: bool = False,
        join_moderation: bool = False,
        default_role: str = "member",
    ) -> dict[str, Any]:
        """Create a new chat. ``chats/createChat``

        Returns ``{"ok": True, "sn": "<chat_id>"}`` on success.
        The returned ``sn`` is the new chat's ID — use it as ``chat_id``
        on subsequent ``/chats/*`` and ``/messages/*`` calls.

        .. warning::
           This is a **private (myteam_only) endpoint**. It is available
           on the server but disabled by default for new bots.

           If the server returns ``{"ok": false, "description":
           "Method not allowed"}``, it means **the endpoint exists but
           your bot is not on the allowlist** — ask the platform admin
           or your integrator team to enable ``chats/createChat`` for
           this bot. (Distinct from ``"Unknown method"``, which would
           mean the endpoint doesn't exist on the server at all.)

           - Cloud ``myteam.mail.ru``: enable via MetaBot, or by request
             to Mail.ru support if MetaBot's toggle is insufficient.
           - On-premises: open a ticket with your integrators / platform
             administrators to enable the method for this bot.

        :param name: Chat title (required).
        :param about: Description.
        :param rules: Chat rules text shown to new members.
        :param members: Initial members (user IDs / emails). Each is
            wire-encoded as ``{"sn": id}``.
        :param public: Public group, joinable by link.
        :param join_moderation: Joining requires admin approval.
        :param default_role: Default role for new members. **Only two
            values are accepted by the server**:

            - ``"member"`` — regular group chat (default).
            - ``"readonly"`` — channel: non-admin members can only read.

            Other strings (``"admin"``, ``"moder"``, etc.) are
            **silently ignored or rejected** — there is no way to grant
            admin/moderator rights via this parameter. Per Bot API
            i18n strings (``teams.vk.com/botapi/lang_config_en.json``):
            *"Should chat be group or channel ('member' for group,
            'readonly' for channel)"*.

            To grant admin to an existing member, see the on-premises
            ``rapi/modChatMember`` workaround documented at
            https://workspace.vk.ru/docs/on-premises/vk-teams/faq-exploitation/
            (server-side, requires ``admin_key`` — not callable from
            a bot token).
        """
        return await self._request(
            "chats/createChat",
            self._params(
                name=name,
                about=about,
                rules=rules,
                members=[{"sn": m} for m in (members or [])],
                public=public,
                joinModeration=join_moderation,
                defaultRole=default_role,
            ),
        )

    async def set_chat_avatar(
        self,
        chat_id: str,
        file: InputFile | BinaryIO,
    ) -> APIResponse:
        """Set chat avatar. ``chats/avatar/set``"""
        params = self._params(chatId=chat_id)
        data = await self._upload("chats/avatar/set", params, file)
        return APIResponse.model_validate(data)

    async def send_actions(self, chat_id: str, actions: str) -> APIResponse:
        """Send chat actions (typing, looking). ``chats/sendActions``"""
        data = await self._request(
            "chats/sendActions",
            self._params(chatId=chat_id, actions=actions),
        )
        return APIResponse.model_validate(data)

    async def pin_message(self, chat_id: str, msg_id: str) -> APIResponse:
        """Pin a message. ``chats/pinMessage``"""
        data = await self._request(
            "chats/pinMessage",
            self._params(chatId=chat_id, msgId=msg_id),
        )
        return APIResponse.model_validate(data)

    async def unpin_message(self, chat_id: str, msg_id: str) -> APIResponse:
        """Unpin a message. ``chats/unpinMessage``"""
        data = await self._request(
            "chats/unpinMessage",
            self._params(chatId=chat_id, msgId=msg_id),
        )
        return APIResponse.model_validate(data)

    # ── Files ─────────────────────────────────────────────────────────

    async def get_file_info(self, file_id: str) -> File:
        """Get file info. ``files/getInfo``"""
        data = await self._request(
            "files/getInfo",
            self._params(fileId=file_id),
        )
        return File.model_validate(data)

    async def download(
        self,
        file: Any,
        destination: str | Path | None = None,
        **kwargs: Any,
    ) -> bytes | Path:
        """aiogram‑style download. Accepts a file object **or** a file_id.

        *file* may be anything carrying a ``file_id`` (a message attachment
        :class:`~vkworkspace.types.message.FilePayload`, a
        :class:`~vkworkspace.types.file.File`) or a raw ``file_id`` string.

        Example::

            await bot.download(message.files[0], "/downloads/")
            await bot.download(file_id)
        """
        file_id = getattr(file, "file_id", None) or file
        if not isinstance(file_id, str) or not file_id:
            raise ValueError(f"Cannot resolve a file_id from {file!r}")
        return await self.download_file(file_id, destination, **kwargs)

    async def download_file(
        self,
        file_id: str,
        destination: str | Path | None = None,
        *,
        filename: str | None = None,
        append_token: bool = True,
        chunk_size: int = 64 * 1024,
    ) -> bytes | Path:
        """Download a file by its ``file_id``. ``files/getInfo`` + GET.

        Resolves the (unsigned) download URL via :meth:`get_file_info`, then
        streams the file from the VK Teams **file host** (a different host than
        the Bot API, e.g. ``ub.<company>.teams…``).

        .. important::
            The download URL carries its access token in the **query string**,
            and that token contains a ``:`` (on‑prem tokens look like
            ``001.123.456:789``). It **must** be sent verbatim — passing it
            through ``httpx2``/``requests`` ``params=`` percent‑encodes ``:`` to
            ``%3A`` and the file host answers **HTTP 500**. This method appends
            the token to the URL *string* itself, so it is sent as‑is. This is
            the usual cause of "download returns 500 nine times out of ten".

        Args:
            file_id: The file's ID (from a message part or ``File.file_id``).
            destination: Where to save. ``None`` → return the file as ``bytes``.
                A **directory** → save as ``<dir>/<filename>`` and return the
                :class:`~pathlib.Path`. A **file path** → save there and return it.
            filename: Override the name used when *destination* is a directory.
                Defaults to the server's filename, else the URL's basename.
            append_token: Append ``?token=<bot_token>`` to the URL (default
                ``True`` — required by most installations). Set ``False`` if the
                URL is already signed.
            chunk_size: Streaming chunk size in bytes (default 64 KiB).

        Returns:
            ``bytes`` if *destination* is ``None``, otherwise the saved
            :class:`~pathlib.Path`.

        Raises:
            FileDownloadError: If the file host does not return the file.

        Examples::

            # Into memory
            data = await bot.download_file(file_id)

            # Into a directory (keeps the server filename)
            path = await bot.download_file(file_id, "/downloads/")

            # To an exact path
            await bot.download_file(file_id, "/tmp/report.pdf")
        """
        info = await self.get_file_info(file_id)
        if not info.url:
            raise FileDownloadError(
                url="",
                message=f"files/getInfo returned no download URL for file_id={file_id!r}",
            )
        name = filename or info.filename or _filename_from_url(info.url) or file_id
        return await self.download_file_by_url(
            info.url,
            destination,
            filename=name,
            append_token=append_token,
            chunk_size=chunk_size,
        )

    async def download_file_by_url(
        self,
        url: str,
        destination: str | Path | None = None,
        *,
        filename: str | None = None,
        append_token: bool = True,
        chunk_size: int = 64 * 1024,
    ) -> bytes | Path:
        """Download a file from an already‑known URL. GET (streamed).

        Use this when you already have the URL (e.g. from a message file part)
        and want to skip the extra ``files/getInfo`` round‑trip. See
        :meth:`download_file` for the ``:`` / ``%3A`` token caveat — the token
        is appended to the URL *string*, never via ``params=``.

        Args mirror :meth:`download_file`. If *url* already contains a
        ``token=`` query parameter, no token is appended regardless of
        *append_token*.
        """
        target = url
        if append_token and "token=" not in urlsplit(url).query:
            sep = "&" if urlsplit(url).query else "?"
            target = f"{url}{sep}token={self.token}"

        name = filename or _filename_from_url(url) or "file"
        max_attempts = (self.retry_on_5xx or 0) + 1
        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            session = await self.get_session()
            try:
                # NOTE: `target` is passed as a full string on purpose so httpx2
                # does not re-encode the `:` inside the token (see docstring).
                async with self._tracked(session), session.stream("GET", target) as resp:
                    if resp.status_code >= 500 and attempt < max_attempts - 1:
                        last_exc = FileDownloadError(
                            url=target,
                            message=f"HTTP {resp.status_code} from file host",
                        )
                        delay = _jittered(min(2**attempt, 8))
                        logger.warning(
                            "File download 5xx (attempt %d/%d), retrying in %.1fs...",
                            attempt + 1,
                            max_attempts,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if resp.status_code != 200:
                        await resp.aread()
                        raise FileDownloadError(
                            url=target,
                            message=(
                                f"HTTP {resp.status_code} from file host "
                                f"(is the token valid / not percent‑encoded?)"
                            ),
                        )
                    return await self._stream_to(resp, destination, name, chunk_size)
            except httpx2.HTTPError as exc:
                if isinstance(exc, httpx2.ConnectError) and _is_ssl_verification_error(exc):
                    host = urlsplit(target).hostname
                    raise SSLVerificationError(
                        friendly_ssl_hint(host, mincifry=self.mincifry)
                    ) from exc
                if attempt >= max_attempts - 1:
                    raise FileDownloadError(url=target, message=_describe(exc)) from exc
                last_exc = exc
                await asyncio.sleep(_jittered(min(2**attempt, 8)))

        raise FileDownloadError(  # pragma: no cover - loop always returns/raises
            url=target,
            message=str(last_exc) if last_exc else "download failed",
        )

    @staticmethod
    async def _stream_to(
        resp: httpx2.Response,
        destination: str | Path | None,
        filename: str,
        chunk_size: int,
    ) -> bytes | Path:
        """Consume *resp* body: to ``bytes`` (destination=None) or to disk."""
        if destination is None:
            chunks = [chunk async for chunk in resp.aiter_bytes(chunk_size)]
            return b"".join(chunks)

        def prepare() -> Path:
            dest = Path(destination)
            if dest.is_dir() or str(destination).endswith(("/", "\\")):
                dest.mkdir(parents=True, exist_ok=True)
                return dest / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            return dest

        # Disk I/O runs in a worker thread: a slow disk must not stall other chats.
        dest = await asyncio.to_thread(prepare)
        fp = await asyncio.to_thread(dest.open, "wb")
        try:
            async for chunk in resp.aiter_bytes(chunk_size):
                await asyncio.to_thread(fp.write, chunk)
        finally:
            await asyncio.to_thread(fp.close)
        return dest

    # ── Threads ───────────────────────────────────────────────────────
    #
    # All three thread endpoints are undocumented in the public OpenAPI
    # spec at teams.vk.com/botapi/ but present in the official Mail.ru
    # bot-python library and confirmed working on modern VK Teams
    # servers (cloud myteam.mail.ru, recent paid on-premises builds).
    #
    # On legacy / older on-premises installations one or more thread
    # methods may return ``"Unknown method"`` — that's a server build
    # issue (the method isn't compiled in), not a bot permission. Ask
    # your platform admin to upgrade the server. Distinct from
    # ``"Method not allowed"`` which is ACL-gated and fixable by
    # toggling the bot's allowlist.

    async def threads_get_subscribers(
        self,
        thread_id: str,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> ThreadSubscribers:
        """Get thread subscribers. ``threads/subscribers/get``

        See module-level Threads note for availability caveats.
        """
        data = await self._request(
            "threads/subscribers/get",
            self._params(
                threadId=thread_id,
                pageSize=page_size,
                cursor=cursor,
            ),
        )
        return ThreadSubscribers.model_validate(data)

    async def threads_autosubscribe(
        self,
        chat_id: str,
        enable: bool,
        with_existing: bool = False,
    ) -> APIResponse:
        """Toggle thread autosubscribe. ``threads/autosubscribe``

        Enable / disable automatic subscription to every new thread in
        the chat. ``with_existing=True`` also retroactively subscribes
        members to all existing threads in the chat.

        See module-level Threads note for availability caveats.
        """
        data = await self._request(
            "threads/autosubscribe",
            self._params(
                chatId=chat_id,
                enable=enable,
                withExisting=with_existing,
            ),
        )
        return APIResponse.model_validate(data)

    async def threads_add(self, chat_id: str, msg_id: str) -> Thread:
        """Create thread from message. ``threads/add``

        Anchor a new thread to the message ``msg_id`` in chat ``chat_id``.
        Returns ``Thread`` with ``thread_id`` (the thread's own chat ID,
        format ``XXXXXXXXX@chat.agent``). To post into the thread later,
        use :meth:`send_text` with ``parent_topic``.

        See module-level Threads note for availability caveats.
        """
        data = await self._request(
            "threads/add",
            self._params(chatId=chat_id, msgId=msg_id),
        )
        return Thread.model_validate(data)
