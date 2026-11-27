"""Network failures: retries, connection-pool replacement, long-poll deadline,
and the polling loop staying alive.

No real network: clients run on ``httpx2.MockTransport``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from vkworkspace import Bot, Dispatcher
from vkworkspace.client.bot import _ClientState
from vkworkspace.exceptions import (
    VKTeamsAPIError,
    VKTeamsHTTPError,
    VKTeamsNetworkError,
    VKTeamsOutcomeUnknown,
)
from vkworkspace.types.event import Update

API_URL = "https://mock.vkteams.test/bot/v1"
TOKEN = "test-token-001"


@pytest.fixture(autouse=True)
def backoff_delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Retry pauses take no time and have no random part; the requested delays are recorded."""
    delays: list[float] = []
    real_sleep = asyncio.sleep
    monkeypatch.setattr(random, "uniform", lambda low, high: high)

    async def fake_sleep(delay: float, *args: Any) -> None:
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


def _own_clients(
    bot: Bot, handler: Callable[..., Any], limit: int = 100
) -> list[httpx2.AsyncClient]:
    """Make *bot* build its own clients on a mock transport; returns the list of them."""
    created: list[httpx2.AsyncClient] = []

    def factory(max_connections: int = limit) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        bot._clients[client] = _ClientState(limit=min(limit, max_connections))
        created.append(client)
        return client

    bot._new_client = factory  # type: ignore[method-assign]
    return created


def _script(*steps: Any) -> tuple[Callable[[httpx2.Request], httpx2.Response], list[str]]:
    """Handler that plays *steps* in order: an exception is raised, a dict is a 200 JSON,
    an int is that status. The last step repeats. Returns the handler and the call log."""
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path.split("/bot/v1/")[-1])
        step = steps[min(len(calls), len(steps)) - 1]
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, int):
            return httpx2.Response(step)
        return httpx2.Response(200, json=step)

    return handler, calls


OK = {"ok": True, "msgId": "m1"}


# ── two clients ────────────────────────────────────────────────────────


class TestSessions:
    async def test_client_timeouts(self):
        bot = Bot(token=TOKEN, api_url=API_URL, timeout=30, poll_time=60)
        session = await bot.get_session()
        assert session.timeout.read == 30
        assert session.timeout.connect == 10
        assert session.timeout.pool == 10
        await bot.close()
        assert session.is_closed

    async def test_long_poll_gets_its_own_read_timeout(self):
        seen: dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen[request.url.path.rsplit("/", 1)[-1]] = request.extensions["timeout"]
            return httpx2.Response(200, json={"ok": True, "events": [], "msgId": "m1"})

        bot = Bot(token=TOKEN, api_url=API_URL, timeout=30, poll_time=60)
        created = _own_clients(bot, handler)
        await bot.get_events()
        await bot.get_events(poll_time=10)
        assert seen["get"]["read"] == 40  # pollTime + timeout, per call
        assert len(created) == 1
        await bot.close()

    async def test_long_poll_has_a_pool_of_its_own(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script({"ok": True, "events": [], "msgId": "m1"})
        created = _own_clients(bot, handler)
        await bot.get_events()
        await bot.send_text("c@x", "hi")
        assert calls == ["events/get", "messages/sendText"]
        assert len(created) == 2
        assert bot._poll_session is created[0]
        assert bot._session is created[1]
        assert bot._clients[created[0]].limit == 4
        await bot.close()
        assert created[0].is_closed
        assert created[1].is_closed

    async def test_sends_that_fill_the_pool_do_not_block_the_long_poll(self):
        release = asyncio.Event()

        async def handler(request: httpx2.Request) -> httpx2.Response:
            if request.url.path.endswith("/messages/sendText"):
                await release.wait()  # every send hangs on the server
            return httpx2.Response(200, json={"ok": True, "events": [], "msgId": "m1"})

        bot = Bot(token=TOKEN, api_url=API_URL)
        created = _own_clients(bot, handler)
        sends = [asyncio.create_task(bot.send_text("c@x", f"m{i}")) for i in range(20)]
        await asyncio.sleep(0)
        assert await asyncio.wait_for(bot.get_events(), timeout=2) == []
        assert len(created) == 2
        release.set()
        await asyncio.gather(*sends)
        await bot.close()

    async def test_client_assigned_from_outside_serves_everything(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script({"ok": True, "events": [], "msgId": "m1"})
        bot._session = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        assert await bot.get_events() == []
        await bot.send_text("c@x", "hi")
        assert calls == ["events/get", "messages/sendText"]
        await bot.close()
        assert bot._session.is_closed


# ── retries ────────────────────────────────────────────────────────────


class TestRetries:
    @pytest.mark.parametrize(
        "error",
        [
            httpx2.ConnectError(""),
            httpx2.ConnectTimeout(""),
            httpx2.PoolTimeout(""),
            httpx2.ProxyError("502 Bad Gateway"),
        ],
    )
    async def test_request_that_was_not_sent_is_repeated_for_sends(self, error):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(error, OK)
        _own_clients(bot, handler)
        resp = await bot.send_text("c@x", "hi")
        assert resp.msg_id == "m1"
        assert calls == ["messages/sendText"] * 2
        await bot.close()

    @pytest.mark.parametrize(
        "error",
        [
            httpx2.RemoteProtocolError("Server disconnected without sending a response."),
            httpx2.ReadTimeout(""),
            httpx2.ReadError(""),
        ],
    )
    async def test_unknown_outcome_is_repeated_for_repeatable_methods(self, error):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(error, {"ok": True})
        _own_clients(bot, handler)
        await bot.set_chat_title("c@x", "title")
        assert calls == ["chats/setTitle"] * 2
        await bot.close()

    @pytest.mark.parametrize(
        "error",
        [
            httpx2.RemoteProtocolError("Server disconnected without sending a response."),
            httpx2.ReadTimeout(""),
        ],
    )
    async def test_unknown_outcome_is_not_repeated_for_sends(self, error):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(error, OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsNetworkError) as info:
            await bot.send_text("c@x", "hi")
        assert info.value.original is error
        assert calls == ["messages/sendText"]
        await bot.close()

    async def test_request_timed_out_description(self):
        timed_out = {"ok": False, "description": "Request timed out"}

        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(timed_out, {"ok": True})
        _own_clients(bot, handler)
        await bot.set_chat_title("c@x", "title")
        assert calls == ["chats/setTitle"] * 2
        await bot.close()

        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(timed_out, OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsAPIError, match="Request timed out"):
            await bot.send_text("c@x", "hi")
        assert calls == ["messages/sendText"]
        await bot.close()

    async def test_gives_up_after_the_configured_number_of_retries(self, backoff_delays):
        bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=3)
        handler, calls = _script(httpx2.ConnectError(""))
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsNetworkError, match="ConnectError"):
            await bot.send_text("c@x", "hi")
        assert len(calls) == 4
        assert backoff_delays == [1, 2, 4]
        await bot.close()

    async def test_no_retries_when_disabled(self):
        bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=None)
        handler, calls = _script(httpx2.ConnectError(""), OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsNetworkError):
            await bot.send_text("c@x", "hi")
        assert len(calls) == 1
        await bot.close()

    async def test_gateway_timeout_is_not_repeated_for_methods_that_create(self):
        """504 = the gateway stopped waiting; the server may still deliver the message."""
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(504, OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsHTTPError) as info:
            await bot.send_text("c@x", "hi")
        assert info.value.status_code == 504
        assert calls == ["messages/sendText"]
        await bot.close()

        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(504, OK)
        _own_clients(bot, handler)
        await bot.set_chat_title("c@x", "t")
        assert calls == ["chats/setTitle"] * 2
        await bot.close()

    async def test_retries_stay_within_the_deadline_of_the_call(self, monkeypatch):
        """A call that keeps timing out is not repeated past ``timeout + DEADLINE_MARGIN``."""
        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])

        def handler(request: httpx2.Request) -> httpx2.Response:
            clock[0] += 30.0  # the server kept the request for the whole read timeout
            raise httpx2.ReadTimeout("")

        bot = Bot(token=TOKEN, api_url=API_URL, timeout=30, retry_on_5xx=3)
        calls: list[str] = []
        created = _own_clients(bot, lambda request: (calls.append("x"), handler(request))[1])
        with pytest.raises(VKTeamsNetworkError, match="ReadTimeout"):
            await bot.set_chat_title("c@x", "t")
        # 30 s + 30 s is past the 55 s deadline: no third and fourth attempt
        assert len(calls) == 2
        assert not created[0].is_closed  # timeouts of the server say nothing about the pool
        await bot.close()

    async def test_5xx_and_server_error_are_still_repeated(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(502, {"ok": False, "description": "Server error: id=0x1"}, OK)
        _own_clients(bot, handler)
        await bot.send_text("c@x", "hi")
        assert len(calls) == 3
        await bot.close()

    async def test_4xx_and_api_errors_are_not_repeated(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script({"ok": False, "description": "Permission denied"}, OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsAPIError, match="Permission denied"):
            await bot.send_text("c@x", "hi")
        assert len(calls) == 1
        await bot.close()

    async def test_upload_from_a_stream_that_cannot_rewind_is_not_repeated(self):
        class OneShot(io.BytesIO):
            def seekable(self) -> bool:
                return False

        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(502, OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsHTTPError) as info:
            await bot.send_file("c@x", file=OneShot(b"data"))
        assert info.value.status_code == 502
        assert len(calls) == 1
        await bot.close()

    async def test_upload_from_bytes_is_repeated_with_the_full_body(self):
        bodies: list[bytes] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            bodies.append(request.read())
            return httpx2.Response(502) if len(bodies) == 1 else httpx2.Response(200, json=OK)

        bot = Bot(token=TOKEN, api_url=API_URL)
        _own_clients(bot, handler)
        await bot.send_file("c@x", file=io.BytesIO(b"payload-bytes"))
        assert len(bodies) == 2
        assert b"payload-bytes" in bodies[0]
        assert b"payload-bytes" in bodies[1]
        await bot.close()


# ── connection-pool replacement ────────────────────────────────────────


class TestPoolReplacement:
    async def test_pool_timeout_replaces_the_client(self, caplog):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(httpx2.PoolTimeout(""), OK)
        created = _own_clients(bot, handler)
        with caplog.at_level(logging.WARNING, logger="vkworkspace.client.bot"):
            await bot.send_text("c@x", "hi")
        assert len(calls) == 2
        assert len(created) == 2
        assert created[0].is_closed
        assert bot._session is created[1]
        assert created[0] not in bot._clients
        assert "Replacing the HTTP connection pool" in caplog.text
        await bot.close()

    async def test_pool_timeout_under_real_load_keeps_the_client(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        client = bot._new_client()
        state = bot._clients[client]
        state.in_flight = state.limit  # the pool is full of live requests
        with pytest.raises(httpx2.PoolTimeout):
            async with bot._tracked(client):
                raise httpx2.PoolTimeout("")
        assert not state.retired
        assert state.in_flight == state.limit
        await bot.close()

    async def test_failed_connections_replace_the_client_before_the_pool_fills(self):
        bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=None)
        handler, _calls = _script(httpx2.ConnectError(""))
        created = _own_clients(bot, handler, limit=4)
        # a pool of 4 slots is replaced after 2 failed connections — half of it
        for _ in range(2):
            with pytest.raises(VKTeamsNetworkError):
                await bot.get_events()
        assert created[0].is_closed
        assert bot._poll_session is None
        with pytest.raises(VKTeamsNetworkError):
            await bot.get_events()
        assert len(created) == 2
        await bot.close()

    async def test_retired_client_is_closed_after_its_last_request(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        client = bot._new_client()
        bot._session = client
        release = asyncio.Event()

        async def in_flight() -> None:
            async with bot._tracked(client):
                await release.wait()

        task = asyncio.create_task(in_flight())
        await asyncio.sleep(0)
        bot._retire(client, "test")
        assert bot._session is None
        assert not client.is_closed
        release.set()
        await task
        assert client.is_closed
        await bot.close()

    async def test_client_assigned_from_outside_is_never_replaced(self):
        bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=None)
        handler, _calls = _script(httpx2.PoolTimeout(""))
        outside = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        bot._session = outside
        with pytest.raises(VKTeamsNetworkError, match="PoolTimeout"):
            await bot.send_text("c@x", "hi")
        assert bot._session is outside
        assert not outside.is_closed
        await bot.close()


# ── long-poll deadline ─────────────────────────────────────────────────


class TestLongPollDeadline:
    async def test_hung_long_poll_is_abandoned(self):
        async def handler(request: httpx2.Request) -> httpx2.Response:
            await asyncio.Event().wait()  # never answers
            raise AssertionError("unreachable")

        bot = Bot(token=TOKEN, api_url=API_URL, timeout=0.05, poll_time=0, retry_on_5xx=None)
        bot.DEADLINE_MARGIN = 0.05
        created = _own_clients(bot, handler)
        with pytest.raises(VKTeamsNetworkError, match="events/get got no response"):
            await asyncio.wait_for(bot.get_events(), timeout=5)
        assert created[0].is_closed
        assert bot._poll_session is None
        await bot.close()

    async def test_hung_api_call_is_abandoned(self):
        async def handler(request: httpx2.Request) -> httpx2.Response:
            await asyncio.Event().wait()  # never answers
            raise AssertionError("unreachable")

        bot = Bot(token=TOKEN, api_url=API_URL, timeout=0.05, retry_on_5xx=None)
        bot.DEADLINE_MARGIN = 0.05
        created = _own_clients(bot, handler)
        with pytest.raises(VKTeamsNetworkError, match="chats/setTitle got no response"):
            await asyncio.wait_for(bot.set_chat_title("c@x", "t"), timeout=5)
        assert created[0].is_closed
        await bot.close()

    async def test_upload_has_no_deadline(self):
        async def handler(request: httpx2.Request) -> httpx2.Response:
            await asyncio.sleep(0)  # the fake clock makes this instant; real time passes below
            for _ in range(20):
                await asyncio.sleep(0)
            return httpx2.Response(200, json=OK)

        bot = Bot(token=TOKEN, api_url=API_URL, timeout=0.0001)
        bot.DEADLINE_MARGIN = 0.0
        _own_clients(bot, handler)
        resp = await bot.send_file("c@x", file=io.BytesIO(b"data"))
        assert resp.msg_id == "m1"
        await bot.close()


# ── an event that does not parse ───────────────────────────────────────


def _raw_event(event_id: Any, **extra: Any) -> dict[str, Any]:
    return {"eventId": event_id, "type": "newMessage", "payload": {}, **extra}


class TestUnreadableEvent:
    async def test_bad_event_is_skipped_and_the_rest_of_the_batch_is_delivered(self, caplog):
        bad = {"eventId": 2, "payload": {"text": "no type"}}
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, _calls = _script({"ok": True, "events": [_raw_event(1), bad, _raw_event(3)]})
        bot._session = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        with caplog.at_level(logging.ERROR, logger="vkworkspace.client.bot"):
            events = await bot.get_events()
        assert [e.event_id for e in events] == [1, 3]
        assert bot._last_event_id == 3
        assert "Event 2 skipped" in caplog.text
        assert "type: Field required" in caplog.text
        await bot.close()

    async def test_polling_moves_past_a_bad_event_instead_of_asking_for_it_forever(self):
        asked: list[str] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            last = request.read().decode().split("lastEventId=")[1].split("&")[0]
            asked.append(last)
            batch = [{"eventId": 7, "payload": {}}] if last == "0" else []
            return httpx2.Response(200, json={"ok": True, "events": batch})

        bot = Bot(token=TOKEN, api_url=API_URL)
        bot._session = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        assert await bot.get_events() == []
        assert await bot.get_events() == []
        assert asked == ["0", "7"]  # the second poll asks for what comes after the bad event
        await bot.close()

    async def test_bad_event_without_an_id_does_not_spin(self, backoff_delays):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, _calls = _script({"ok": True, "events": [{"type": "newMessage"}]})
        bot._session = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        assert await bot.get_events() == []
        assert backoff_delays == [1.0]
        await bot.close()


# ── polling loop ───────────────────────────────────────────────────────


def _update(event_id: int) -> Update:
    return Update.model_validate(
        {
            "eventId": event_id,
            "type": "newMessage",
            "payload": {
                "msgId": str(event_id),
                "chat": {"chatId": "u@x", "type": "private"},
                "from": {"userId": "u@x", "firstName": "U"},
                "text": f"text {event_id}",
                "timestamp": 1,
            },
        }
    )


class _ScriptedBot:
    """Stand-in for Bot: ``get_events`` plays *steps*, then stops the dispatcher."""

    token = TOKEN

    def __init__(self, dp: Dispatcher, *steps: Any) -> None:
        self.dp = dp
        self.steps = list(steps)
        self.calls = 0

    async def get_events(self) -> list[Update]:
        self.calls += 1
        if not self.steps:
            self.dp._running = False
            return []
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class TestPollingLoop:
    async def test_network_errors_do_not_stop_polling(self, backoff_delays):
        dp = Dispatcher()
        dp._running = True
        bot = _ScriptedBot(dp, httpx2.PoolTimeout(""), httpx2.ConnectError(""), [])
        await dp._polling(bot)
        assert bot.calls == 4
        assert backoff_delays[:2] == [1, 2]

    async def test_pauses_have_a_random_part(self, monkeypatch, backoff_delays):
        monkeypatch.setattr(random, "uniform", lambda low, high: low)
        dp = Dispatcher()
        dp._running = True
        bot = _ScriptedBot(dp, httpx2.ConnectError(""), httpx2.ConnectError(""), [])
        await dp._polling(bot)
        assert backoff_delays[:2] == [0.5, 1.0]  # from a half of the pause to all of it

    async def test_http_error_of_the_server_is_a_polling_error(self, caplog):
        """A server answering 404 or 5xx is polled with pauses and is seen in the log."""
        dp = Dispatcher()
        dp._running = True
        bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=None)
        handler, calls = _script(404, 502, {"ok": True, "events": []})
        bot._session = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

        async def poll() -> list[Update]:
            if len(calls) == 3:
                dp._running = False
            return await Bot.get_events(bot)

        bot.get_events = poll  # type: ignore[method-assign]
        with caplog.at_level(logging.INFO, logger="vkworkspace.dispatcher.dispatcher"):
            await dp._polling(bot)
        assert (
            "Polling error (1): VKTeamsHTTPError: HTTP error in events/get: HTTP 404" in caplog.text
        )
        assert (
            "Polling error (2): VKTeamsHTTPError: HTTP error in events/get: HTTP 502" in caplog.text
        )
        assert "Connection restored after 2 retries" in caplog.text
        await bot.close()

    async def test_backoff_is_capped(self, backoff_delays):
        dp = Dispatcher()
        dp._running = True
        bot = _ScriptedBot(dp, *[httpx2.ConnectError("")] * 8)
        await dp._polling(bot)
        assert max(backoff_delays) == dp.POLLING_BACKOFF_MAX == 5

    async def test_long_outage_is_logged_as_error(self, caplog):
        dp = Dispatcher()
        dp._running = True
        bot = _ScriptedBot(dp, *[httpx2.PoolTimeout("")] * 10, [])
        with caplog.at_level(logging.INFO, logger="vkworkspace.dispatcher.dispatcher"):
            await dp._polling(bot)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 10  # every failed attempt is visible
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "10 polling errors in a row" in errors[0].getMessage()
        assert "PoolTimeout" in errors[0].getMessage()
        assert "Connection restored after 10 retries" in caplog.text

    async def test_error_without_a_message_is_named_in_the_log(self, caplog):
        dp = Dispatcher()
        dp._running = True
        bot = _ScriptedBot(dp, httpx2.PoolTimeout(""))
        with caplog.at_level(logging.WARNING, logger="vkworkspace.dispatcher.dispatcher"):
            await dp._polling(bot)
        assert "Polling error (1): PoolTimeout" in caplog.text

    async def test_cancelling_the_task_stops_polling(self):
        dp = Dispatcher()
        dp._running = True
        started = asyncio.Event()

        class Hanging:
            token = TOKEN

            async def get_events(self) -> list[Update]:
                started.set()
                await asyncio.Event().wait()
                return []

        task = asyncio.create_task(dp._polling(Hanging()))
        await started.wait()
        task.cancel()
        await asyncio.wait_for(task, timeout=2)
        assert task.done()
        assert not task.cancelled()

    async def test_failed_update_does_not_drop_the_rest_of_the_batch(self, monkeypatch, caplog):
        dp = Dispatcher()
        dp._running = True
        seen: list[int] = []

        async def feed_update(bot: Any, update: Update) -> None:
            if update.event_id == 1:
                raise RuntimeError("storage is down")
            seen.append(update.event_id)

        monkeypatch.setattr(dp, "feed_update", feed_update)
        bot = _ScriptedBot(dp, [_update(1), _update(2), _update(3)])
        with caplog.at_level(logging.ERROR, logger="vkworkspace.dispatcher.dispatcher"):
            await dp._polling(bot)
        assert seen == [2, 3]
        assert "Update 1 was not processed" in caplog.text
        assert bot.calls == 2


# ── a call that was not repeated because its outcome is unknown ─────────

TIMED_OUT = {"ok": False, "description": "Request timed out"}
DROPPED = "Server disconnected without sending a response."


class TestOutcomeUnknown:
    @pytest.mark.parametrize(
        ("step", "also"),
        [
            (httpx2.ReadTimeout(""), VKTeamsNetworkError),
            (httpx2.RemoteProtocolError(DROPPED), VKTeamsNetworkError),
            (504, VKTeamsHTTPError),
            (TIMED_OUT, VKTeamsAPIError),
        ],
        ids=["read-timeout", "dropped", "http-504", "request-timed-out"],
    )
    async def test_send_raises_one_class_that_is_also_the_old_one(self, step, also):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(step, OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsOutcomeUnknown) as info:
            await bot.send_text("c@x", "hi")
        err = info.value
        assert isinstance(err, also)  # `except VKTeamsNetworkError` etc. keep working
        assert calls == ["messages/sendText"]  # not repeated
        assert err.method == "messages/sendText"
        assert "outcome is unknown" in str(err)
        await bot.close()

    async def test_fields_and_cause(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, _calls = _script(httpx2.ReadTimeout(""))
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsOutcomeUnknown) as info:
            await bot.send_file("c@x", file_id="f1")
        err = info.value
        assert err.message == "ReadTimeout"
        assert isinstance(err.original, httpx2.ReadTimeout)
        assert err.__cause__ is err.original
        await bot.close()

        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, _calls = _script(504)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsOutcomeUnknown) as info:
            await bot.send_voice("c@x", file_id="v1")
        assert isinstance(info.value, VKTeamsHTTPError)
        assert info.value.status_code == 504
        assert info.value.message == "HTTP 504"
        assert isinstance(info.value.original, httpx2.HTTPStatusError)
        await bot.close()

        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, _calls = _script(TIMED_OUT)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsOutcomeUnknown) as info:
            await bot.send_text("c@x", "hi")
        assert info.value.message == "Request timed out"
        assert info.value.original is None
        assert info.value.__cause__ is None
        await bot.close()

    async def test_deadline_of_a_send_is_an_unknown_outcome(self):
        async def handler(request: httpx2.Request) -> httpx2.Response:
            await asyncio.Event().wait()  # never answers
            raise AssertionError("unreachable")

        bot = Bot(token=TOKEN, api_url=API_URL, timeout=0.05)
        bot.DEADLINE_MARGIN = 0.05
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsOutcomeUnknown, match="got no response"):
            await asyncio.wait_for(bot.send_text("c@x", "hi"), timeout=5)
        await bot.close()

    async def test_request_that_was_not_sent_is_retried_then_is_a_plain_error(self):
        bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=2)
        handler, calls = _script(httpx2.ConnectError(""))
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsNetworkError) as info:
            await bot.send_text("c@x", "hi")
        assert not isinstance(info.value, VKTeamsOutcomeUnknown)
        assert len(calls) == 3
        await bot.close()

    async def test_not_sent_then_unknown_is_an_unknown_outcome(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(httpx2.ConnectError(""), httpx2.ReadTimeout(""), OK)
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsOutcomeUnknown):
            await bot.send_text("c@x", "hi")
        assert len(calls) == 2
        await bot.close()

    async def test_repeatable_method_keeps_the_old_errors(self):
        bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=1)
        handler, calls = _script(httpx2.ReadTimeout(""))
        _own_clients(bot, handler)
        with pytest.raises(VKTeamsNetworkError) as info:
            await bot.set_chat_title("c@x", "t")
        assert not isinstance(info.value, VKTeamsOutcomeUnknown)
        assert len(calls) == 2  # repeated: a repeat cannot create a duplicate
        await bot.close()

    async def test_definite_answers_are_not_an_unknown_outcome(self):
        cases: list[tuple[Any, type[Exception]]] = [
            ({"ok": False, "description": "Permission denied"}, VKTeamsAPIError),
            (403, VKTeamsHTTPError),
        ]
        for step, error in cases:
            bot = Bot(token=TOKEN, api_url=API_URL)
            handler, _calls = _script(step)
            _own_clients(bot, handler)
            with pytest.raises(error) as info:
                await bot.send_text("c@x", "hi")
            assert not isinstance(info.value, VKTeamsOutcomeUnknown)
            await bot.close()

    async def test_middleware_sees_the_unknown_outcome(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, _calls = _script(httpx2.ReadTimeout(""))
        _own_clients(bot, handler)
        seen: list[BaseException] = []

        @bot.request_middleware
        async def spy(make_request: Any, endpoint: str, params: Any, files: Any) -> Any:
            try:
                return await make_request(endpoint, params, files)
            except Exception as exc:
                seen.append(exc)
                raise

        with pytest.raises(VKTeamsOutcomeUnknown):
            await bot.send_text("c@x", "hi")
        assert len(seen) == 1
        assert isinstance(seen[0], VKTeamsOutcomeUnknown)
        await bot.close()


class TestAnswerCallbackQuery:
    @pytest.mark.parametrize(
        "step",
        [{"ok": False, "description": "Server error: id=0x1"}, httpx2.ConnectError(""), 502],
        ids=["server-error", "not-sent", "http-502"],
    )
    async def test_one_attempt_without_retries(self, step, caplog, backoff_delays):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script(step, {"ok": True})
        _own_clients(bot, handler)
        with (
            caplog.at_level(logging.WARNING, logger="vkworkspace.client.bot"),
            pytest.raises((VKTeamsAPIError, VKTeamsNetworkError, VKTeamsHTTPError)),
        ):
            await bot.answer_callback_query("q1", "Готово")
        assert calls == ["messages/answerCallbackQuery"]
        assert backoff_delays == []
        assert "persisted" not in caplog.text
        assert "retrying" not in caplog.text
        await bot.close()

    async def test_answer_still_works(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        handler, calls = _script({"ok": True})
        _own_clients(bot, handler)
        resp = await bot.answer_callback_query("q1", "Готово")
        assert resp.ok
        assert calls == ["messages/answerCallbackQuery"]
        await bot.close()
