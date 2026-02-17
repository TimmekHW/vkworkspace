"""Tests for FSM session timeout in FSMContextMiddleware."""
from __future__ import annotations

import time
from typing import Any

import pytest

from vkworkspace.dispatcher.middlewares.fsm_context import FSMContextMiddleware
from vkworkspace.fsm.state import State, StatesGroup
from vkworkspace.fsm.storage.base import StorageKey
from vkworkspace.fsm.storage.memory import MemoryStorage


class Form(StatesGroup):
    name = State()
    age = State()


class _FakeChat:
    def __init__(self, chat_id: str) -> None:
        self.chat_id = chat_id


class _FakeUser:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id


class _FakeBot:
    token = "test-token-12345"


class _FakeEvent:
    def __init__(self) -> None:
        self.chat = _FakeChat("chat-1")
        self.from_user = _FakeUser("user-1")


def _make_data() -> dict[str, Any]:
    return {"bot": _FakeBot()}


@pytest.mark.asyncio
async def test_no_timeout_by_default() -> None:
    """Without session_timeout the state persists indefinitely."""
    storage = MemoryStorage()
    mw = FSMContextMiddleware(storage=storage)
    event = _FakeEvent()

    key = StorageKey(bot_id="test-token-12345", chat_id="chat-1", user_id="user-1")
    await storage.set_state(key=key, state=Form.name.state)

    captured: dict[str, Any] = {}

    async def handler(ev: Any, data: dict[str, Any]) -> None:
        captured["current_state"] = data["current_state"]

    await mw(handler, event, _make_data())
    assert captured["current_state"] == Form.name.state


@pytest.mark.asyncio
async def test_timeout_clears_expired_session() -> None:
    """Expired FSM session is cleared before handler runs."""
    storage = MemoryStorage()
    mw = FSMContextMiddleware(storage=storage, session_timeout=5.0)
    event = _FakeEvent()

    key = StorageKey(bot_id="test-token-12345", chat_id="chat-1", user_id="user-1")
    await storage.set_state(key=key, state=Form.name.state)

    # Simulate: first interaction stamps the time
    captured: dict[str, Any] = {}

    async def handler(ev: Any, data: dict[str, Any]) -> None:
        captured["current_state"] = data["current_state"]

    await mw(handler, event, _make_data())
    assert captured["current_state"] == Form.name.state  # first time — no timestamp yet

    # Now the state exists and timestamp is stamped (after handler)
    assert key in mw._timestamps

    # Simulate time passing beyond timeout
    mw._timestamps[key] = time.monotonic() - 10.0  # 10 seconds ago

    await mw(handler, event, _make_data())
    assert captured["current_state"] is None  # session expired

    # Storage should be cleared too
    assert await storage.get_state(key=key) is None


@pytest.mark.asyncio
async def test_timeout_keeps_fresh_session() -> None:
    """Fresh FSM session is not cleared."""
    storage = MemoryStorage()
    mw = FSMContextMiddleware(storage=storage, session_timeout=300.0)
    event = _FakeEvent()

    key = StorageKey(bot_id="test-token-12345", chat_id="chat-1", user_id="user-1")
    await storage.set_state(key=key, state=Form.age.state)

    captured: dict[str, Any] = {}

    async def handler(ev: Any, data: dict[str, Any]) -> None:
        captured["current_state"] = data["current_state"]

    # First call — stamps timestamp
    await mw(handler, event, _make_data())
    assert captured["current_state"] == Form.age.state

    # Second call — still fresh
    await mw(handler, event, _make_data())
    assert captured["current_state"] == Form.age.state


@pytest.mark.asyncio
async def test_timeout_cleans_up_on_clear() -> None:
    """When handler clears state, timestamp is removed."""
    storage = MemoryStorage()
    mw = FSMContextMiddleware(storage=storage, session_timeout=60.0)
    event = _FakeEvent()

    key = StorageKey(bot_id="test-token-12345", chat_id="chat-1", user_id="user-1")
    await storage.set_state(key=key, state=Form.name.state)

    async def handler_set(ev: Any, data: dict[str, Any]) -> None:
        pass  # state stays

    await mw(handler_set, event, _make_data())
    assert key in mw._timestamps

    # Handler clears the state
    async def handler_clear(ev: Any, data: dict[str, Any]) -> None:
        await data["state"].clear()

    await mw(handler_clear, event, _make_data())
    assert key not in mw._timestamps


@pytest.mark.asyncio
async def test_timeout_stamps_on_new_state() -> None:
    """When handler sets a new state, timestamp is recorded."""
    storage = MemoryStorage()
    mw = FSMContextMiddleware(storage=storage, session_timeout=60.0)
    event = _FakeEvent()

    key = StorageKey(bot_id="test-token-12345", chat_id="chat-1", user_id="user-1")

    async def handler(ev: Any, data: dict[str, Any]) -> None:
        await data["state"].set_state(Form.name)

    await mw(handler, event, _make_data())
    assert key in mw._timestamps
