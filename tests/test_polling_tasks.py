"""Polling with ``handle_as_tasks``: a stuck handler does not stop polling, updates
of one chat keep their order, the concurrency limit and the wait on stop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from vkworkspace import Dispatcher
from vkworkspace.types.event import Update
from vkworkspace.types.message import Message


def _message(event_id: int, chat: str, text: str = "") -> Update:
    return Update.model_validate(
        {
            "eventId": event_id,
            "type": "newMessage",
            "payload": {
                "msgId": str(event_id),
                "chat": {"chatId": chat, "type": "private"},
                "from": {"userId": chat, "firstName": "U"},
                "text": text or f"m{event_id}",
                "timestamp": 1,
            },
        }
    )


def _callback(event_id: int, chat: str) -> Update:
    return Update.model_validate(
        {
            "eventId": event_id,
            "type": "callbackQuery",
            "payload": {
                "queryId": f"q{event_id}",
                "callbackData": "x",
                "from": {"userId": chat, "firstName": "U"},
                "message": {
                    "msgId": "1",
                    "chat": {"chatId": chat, "type": "private"},
                    "from": {"userId": "bot", "firstName": "B"},
                    "text": "menu",
                    "timestamp": 1,
                },
            },
        }
    )


class _Feed:
    """Stand-in for Bot: hands out *batches*, then keeps polling until stopped."""

    token = "test-token-001"

    def __init__(self, *batches: list[Update]) -> None:
        self.batches = list(batches)
        self.polls = 0

    async def get_events(self) -> list[Update]:
        self.polls += 1
        await asyncio.sleep(0)
        return self.batches.pop(0) if self.batches else []


async def _until(condition: Any, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


async def _stop(dp: Dispatcher, task: asyncio.Task[None]) -> None:
    dp._running = False
    task.cancel()
    await asyncio.wait_for(task, timeout=5)


async def test_stuck_handler_does_not_stop_polling_or_other_chats():
    dp = Dispatcher()
    dp._running = True
    release = asyncio.Event()
    handled: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        if message.chat.chat_id == "stuck@x":
            await release.wait()
        handled.append(message.text)

    bot = _Feed([_message(1, "stuck@x"), _message(2, "a@x")], [_message(3, "b@x")])
    task = asyncio.create_task(dp._polling(bot))
    await _until(lambda: handled == ["m2", "m3"])
    polls = bot.polls
    await _until(lambda: bot.polls > polls + 3)  # polling goes on while a handler hangs

    release.set()
    await _until(lambda: handled == ["m2", "m3", "m1"])
    await _stop(dp, task)


async def test_updates_of_one_chat_are_handled_in_order_one_at_a_time():
    dp = Dispatcher()
    dp._running = True
    order: list[str] = []
    running = 0
    overlap = False

    @dp.message()
    async def on_message(message: Message) -> None:
        nonlocal running, overlap
        running += 1
        overlap = overlap or running > 1
        # earlier updates take longer: without ordering they would finish last
        await asyncio.sleep(0.03 if message.text == "m1" else 0)
        order.append(message.text)
        running -= 1

    bot = _Feed([_message(1, "a@x"), _message(2, "a@x")], [_message(3, "a@x")])
    task = asyncio.create_task(dp._polling(bot))
    await _until(lambda: len(order) == 3)
    assert order == ["m1", "m2", "m3"]
    assert overlap is False
    await _until(lambda: dp._chat_tails == {})  # the chat's queue is forgotten once it is empty
    await _stop(dp, task)


async def test_handler_that_never_returns_does_not_silence_its_chat(caplog):
    dp = Dispatcher()
    dp._running = True
    dp.CHAT_ORDER_TIMEOUT = 0.05
    handled: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        if message.text == "m1":
            await asyncio.Event().wait()  # never returns
        handled.append(message.text)

    # m2, m3 and m4 all arrive while m1 is stuck
    bot = _Feed([_message(1, "a@x"), _message(2, "a@x")], [_message(3, "a@x"), _message(4, "a@x")])
    with caplog.at_level(logging.WARNING, logger="vkworkspace.dispatcher.dispatcher"):
        task = asyncio.create_task(dp._polling(bot, tasks_shutdown_timeout=0.05))
        await _until(lambda: len(handled) == 3)
    assert handled == ["m2", "m3", "m4"]  # still in arrival order
    assert "Chat a@x: a handler has been running for more than 0.05s" in caplog.text
    assert "update 2 is handled without waiting" in caplog.text
    assert "update 3 is handled without waiting" not in caplog.text  # m3 waited for m2, not m1
    await _stop(dp, task)


async def test_slow_handler_keeps_the_order_of_everything_behind_it():
    """The limit is counted from the moment a handler started, not from each arrival."""
    dp = Dispatcher()
    dp._running = True
    dp.CHAT_ORDER_TIMEOUT = 0.05
    handled: list[str] = []
    running = 0
    overlap = False

    @dp.message()
    async def on_message(message: Message) -> None:
        nonlocal running, overlap
        running += 1
        overlap = overlap or running > 1
        await asyncio.sleep(0.03)  # each handler is slow, none is stuck
        handled.append(message.text)
        running -= 1

    bot = _Feed([_message(i, "a@x") for i in range(1, 6)])
    task = asyncio.create_task(dp._polling(bot))
    await _until(lambda: len(handled) == 5)
    assert handled == ["m1", "m2", "m3", "m4", "m5"]
    assert overlap is False
    await _stop(dp, task)


async def test_button_press_is_ordered_with_messages_of_its_chat():
    dp = Dispatcher()
    dp._running = True
    order: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        await asyncio.sleep(0.03)
        order.append("message")

    @dp.callback_query()
    async def on_button(query: Any) -> None:
        order.append("button")

    bot = _Feed([_message(1, "a@x"), _callback(2, "a@x")])
    task = asyncio.create_task(dp._polling(bot))
    await _until(lambda: len(order) == 2)
    assert order == ["message", "button"]
    await _stop(dp, task)


async def test_different_chats_are_handled_at_the_same_time():
    dp = Dispatcher()
    dp._running = True
    started: list[str] = []
    release = asyncio.Event()

    @dp.message()
    async def on_message(message: Message) -> None:
        started.append(message.chat.chat_id)
        await release.wait()

    bot = _Feed([_message(1, "a@x"), _message(2, "b@x"), _message(3, "c@x")])
    task = asyncio.create_task(dp._polling(bot))
    await _until(lambda: sorted(started) == ["a@x", "b@x", "c@x"])
    release.set()
    await _stop(dp, task)


async def test_concurrency_limit():
    dp = Dispatcher()
    dp._running = True
    running = 0
    peak = 0
    done = 0

    @dp.message()
    async def on_message(message: Message) -> None:
        nonlocal running, peak, done
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        done += 1

    bot = _Feed([_message(i, f"chat{i}@x") for i in range(1, 9)])
    task = asyncio.create_task(dp._polling(bot, tasks_concurrency_limit=2))
    await _until(lambda: done == 8)
    assert peak == 2
    await _stop(dp, task)


async def test_handlers_inside_the_polling_loop_when_tasks_are_off():
    dp = Dispatcher()
    dp._running = True
    release = asyncio.Event()
    handled: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        await release.wait()
        handled.append(message.text)

    bot = _Feed([_message(1, "a@x")], [_message(2, "b@x")])
    task = asyncio.create_task(dp._polling(bot, handle_as_tasks=False))
    await _until(lambda: bot.polls == 1)
    await asyncio.sleep(0.05)
    assert bot.polls == 1  # the loop waits for the handler
    assert dp._handler_tasks == set()
    release.set()
    await _until(lambda: handled == ["m1", "m2"])
    await _stop(dp, task)


async def test_failing_handler_is_logged_and_the_rest_is_handled(caplog):
    dp = Dispatcher()
    dp._running = True
    handled: list[str] = []

    async def feed_update(bot: Any, update: Update) -> None:
        if update.event_id == 1:
            raise RuntimeError("storage is down")
        handled.append(str(update.event_id))

    dp.feed_update = feed_update  # type: ignore[method-assign]
    bot = _Feed([_message(1, "a@x"), _message(2, "a@x"), _message(3, "b@x")])
    with caplog.at_level(logging.ERROR, logger="vkworkspace.dispatcher.dispatcher"):
        task = asyncio.create_task(dp._polling(bot))
        await _until(lambda: sorted(handled) == ["2", "3"])
    assert "Update 1 was not processed" in caplog.text
    await _stop(dp, task)


async def test_stop_waits_for_running_handlers():
    dp = Dispatcher()
    dp._running = True
    started = asyncio.Event()
    finished: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        started.set()
        await asyncio.sleep(0.05)
        finished.append(message.text)

    task = asyncio.create_task(dp._polling(_Feed([_message(1, "a@x")])))
    await started.wait()
    await _stop(dp, task)
    assert finished == ["m1"]
    assert dp._handler_tasks == set()


async def test_stop_cancels_handlers_that_outlive_the_timeout(caplog):
    dp = Dispatcher()
    dp._running = True
    started = asyncio.Event()
    cancelled: list[bool] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    task = asyncio.create_task(
        dp._polling(_Feed([_message(1, "a@x")]), tasks_shutdown_timeout=0.05)
    )
    await started.wait()
    with caplog.at_level(logging.WARNING, logger="vkworkspace.dispatcher.dispatcher"):
        await _stop(dp, task)
    assert cancelled == [True]
    assert "1 update(s) were still being handled" in caplog.text
    assert dp._handler_tasks == set()


async def test_stop_leaves_handlers_running_when_told_not_to_wait():
    dp = Dispatcher()
    dp._running = True
    started = asyncio.Event()
    release = asyncio.Event()
    finished: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        started.set()
        await release.wait()
        finished.append(message.text)

    task = asyncio.create_task(
        dp._polling(_Feed([_message(1, "a@x")]), tasks_shutdown_timeout=None)
    )
    await started.wait()
    await _stop(dp, task)
    assert finished == []
    release.set()
    await _until(lambda: finished == ["m1"])


@pytest.mark.parametrize(
    ("update", "key"),
    [
        (_message(1, "a@x"), "a@x"),
        (_callback(2, "b@x"), "b@x"),
        (Update.model_validate({"eventId": 3, "type": "newMessage", "payload": {}}), None),
    ],
)
def test_order_key(update: Update, key: str | None):
    assert Dispatcher._order_key(update) == key


async def test_start_polling_passes_the_options(monkeypatch: pytest.MonkeyPatch):
    dp = Dispatcher()
    seen: dict[str, Any] = {}

    async def polling(bot: Any, **kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(dp, "_polling", polling)

    class Closable:
        async def close(self) -> None:
            return None

    await dp.start_polling(
        Closable(),
        handle_signals=False,
        handle_as_tasks=False,
        tasks_concurrency_limit=5,
        tasks_shutdown_timeout=3,
    )
    assert seen == {
        "handle_as_tasks": False,
        "tasks_concurrency_limit": 5,
        "tasks_shutdown_timeout": 3,
    }


async def test_startup_and_shutdown_hooks_may_be_sync_or_async():
    dp = Dispatcher()
    calls: list[str] = []

    @dp.on_startup
    async def async_start() -> None:
        calls.append("async start")

    @dp.on_startup
    def sync_start() -> None:
        calls.append("sync start")

    @dp.on_shutdown
    async def async_stop() -> None:
        calls.append("async stop")

    @dp.on_shutdown
    def sync_stop() -> None:
        calls.append("sync stop")

    await dp.emit_startup()
    await dp.emit_shutdown()
    assert calls == ["async start", "sync start", "async stop", "sync stop"]


async def test_event_with_an_unexpected_payload_does_not_stop_polling():
    dp = Dispatcher()
    dp._running = True
    handled: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        handled.append(message.text)

    odd = [
        Update.model_validate({"eventId": 1, "type": "newMessage", "payload": {"message": "text"}}),
        Update.model_validate({"eventId": 2, "type": "newMessage", "payload": {"chat": ["x"]}}),
    ]
    task = asyncio.create_task(dp._polling(_Feed(odd, [_message(3, "a@x")])))
    await _until(lambda: "m3" in handled)
    assert not task.done()
    await _stop(dp, task)


async def test_concurrency_limit_does_not_count_updates_waiting_for_their_chat():
    """A chat with a queue of its own does not take the places of other chats."""
    dp = Dispatcher()
    dp._running = True
    release = asyncio.Event()
    handled: list[str] = []

    @dp.message()
    async def on_message(message: Message) -> None:
        if message.chat.chat_id == "busy@x":
            await release.wait()
        handled.append(message.text)

    busy = [_message(i, "busy@x") for i in (1, 2, 3)]
    task = asyncio.create_task(
        dp._polling(_Feed(busy, [_message(4, "other@x")]), tasks_concurrency_limit=2)
    )
    await _until(lambda: handled == ["m4"])  # three queued updates of one chat, limit 2
    release.set()
    await _until(lambda: handled == ["m4", "m1", "m2", "m3"])
    await _stop(dp, task)


async def test_bot_server_stop_waits_for_running_handlers():
    from vkworkspace import Router
    from vkworkspace.server import BotServer

    server = BotServer(token="t", api_url="https://mock.test/bot/v1", host="127.0.0.1", port=0)
    router = Router()
    started = asyncio.Event()
    order: list[str] = []

    @router.message()
    async def on_message(message: Message) -> None:
        started.set()
        await asyncio.sleep(0.05)
        order.append("handler finished")

    server.include_router(router)
    server.on_shutdown(lambda: order.append("shutdown hook"))
    feed = _Feed([_message(1, "a@x")])
    server.bot.get_events = feed.get_events  # type: ignore[method-assign]

    running = asyncio.create_task(server.start())
    await started.wait()
    server.stop()
    await asyncio.wait_for(running, timeout=5)
    assert order == ["handler finished", "shutdown hook"]
