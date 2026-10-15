"""Tests for user resolving: ``bot.get_user`` and name / mention helpers."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from vkworkspace.client.bot import Bot
from vkworkspace.types.chat import ChatInfo
from vkworkspace.types.message import MentionPayload, Message
from vkworkspace.types.user import Contact, UserInfo
from vkworkspace.utils.text import md

TOKEN = "001.3033835949.2221539346:1000001942"
API_URL = "https://api.teams.vkteams.test/bot/v1"
AVATAR = "https://ub.teams.vkteams.test/get/?targetSn=1000001942&size=256"

# Shape of a real chats/getInfo reply for a user: note the ``photo`` key.
USER_REPLY: dict[str, Any] = {
    "ok": True,
    "type": "private",
    "firstName": "Иван",
    "lastName": "Иванов",
    "nick": "ivanov",
    "isBot": False,
    "photo": [{"url": AVATAR}],
}


def _bot(reply: dict[str, Any]) -> tuple[Bot, dict[str, int]]:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert req.url.path.endswith("/chats/getInfo")
        return httpx.Response(200, json=reply)

    bot = Bot(token=TOKEN, api_url=API_URL)
    bot._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return bot, calls


# ── bot.get_user ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_by_email():
    bot, _ = _bot(USER_REPLY)
    user = await bot.get_user("ivanov@company.test")
    await bot.close()

    assert isinstance(user, UserInfo)
    assert user.user_id == "ivanov@company.test"
    assert user.full_name == "Иван Иванов"
    assert user.nick == "ivanov"
    assert user.is_bot is False
    assert user.uin == "1000001942"
    assert user.mention == "@[ivanov@company.test]"


@pytest.mark.asyncio
async def test_get_user_by_nick_uses_uin_as_user_id():
    bot, _ = _bot(USER_REPLY)
    user = await bot.get_user("ivanov")
    await bot.close()
    assert user.user_id == "1000001942"
    assert user.mention == "@[1000001942]"


@pytest.mark.asyncio
async def test_get_user_by_nick_without_avatar_keeps_nick():
    reply = {**USER_REPLY, "photo": []}
    bot, _ = _bot(reply)
    user = await bot.get_user("ivanov")
    await bot.close()
    assert user.uin is None
    assert user.user_id == "ivanov"


@pytest.mark.asyncio
async def test_get_user_is_cached():
    bot, calls = _bot(USER_REPLY)
    await bot.get_user("ivanov@company.test")
    await bot.get_user("ivanov@company.test")
    assert calls["n"] == 1

    await bot.get_user("ivanov@company.test", cache=False)
    assert calls["n"] == 2

    bot.clear_user_cache()
    await bot.get_user("ivanov@company.test")
    assert calls["n"] == 3
    await bot.close()


@pytest.mark.asyncio
async def test_get_user_name():
    bot, _ = _bot(USER_REPLY)
    assert await bot.get_user_name("ivanov@company.test") == "Иван Иванов"
    await bot.close()


@pytest.mark.asyncio
async def test_get_user_rejects_group():
    bot, _ = _bot({"ok": True, "type": "group", "title": "Team"})
    with pytest.raises(ValueError, match="group"):
        await bot.get_user("abc123@chat.agent")
    await bot.close()


# ── ChatInfo.photos accepts both API spellings ──────────────────────────


def test_chat_info_photo_key():
    info = ChatInfo.model_validate({"type": "private", "photo": [{"url": AVATAR}]})
    assert info.photos[0].url == AVATAR


def test_chat_info_photos_key_still_works():
    info = ChatInfo.model_validate({"type": "private", "photos": [{"url": AVATAR}]})
    assert info.photos[0].url == AVATAR


def test_chat_info_full_name():
    info = ChatInfo.model_validate({"type": "private", "firstName": "Иван", "lastName": "Иванов"})
    assert info.full_name == "Иван Иванов"


# ── name / mention helpers on user-like types ───────────────────────────


def test_full_name_fallbacks():
    assert Contact(userId="a@b", firstName="Иван", lastName="Иванов").full_name == "Иван Иванов"
    assert Contact(userId="a@b", firstName="Иван").full_name == "Иван"
    assert Contact(userId="a@b", nick="ivan").full_name == "ivan"
    assert Contact(userId="a@b").full_name == "a@b"
    assert Contact(userId="a@b", firstName="  ", lastName="").full_name == "a@b"


def test_mention_markup():
    c = Contact(userId="ivanov@corp.ru")
    assert c.mention == "@[ivanov@corp.ru]"
    assert c.mention_md == md.mention("ivanov@corp.ru")


def test_mention_payload_helpers():
    m = MentionPayload.model_validate(
        {"userId": "petrov@corp.ru", "firstName": "Пётр", "lastName": "Петров"}
    )
    assert m.full_name == "Пётр Петров"
    assert m.mention == "@[petrov@corp.ru]"


def test_message_mentioned_user_ids():
    msg = Message.model_validate(
        {
            "msgId": "1",
            "chat": {"chatId": "c@chat", "type": "group"},
            "text": "@[a@corp.ru] @[b@corp.ru] привет",
            "parts": [
                {"type": "mention", "payload": {"userId": "a@corp.ru", "firstName": "A"}},
                {"type": "mention", "payload": {"userId": "b@corp.ru", "firstName": "B"}},
                {"type": "file", "payload": {"fileId": "F", "type": "image"}},
            ],
        }
    )
    assert msg.mentioned_user_ids == ["a@corp.ru", "b@corp.ru"]
    assert [m.full_name for m in msg.mentions] == ["A", "B"]


# ── VKT_PROXY environment variable ──────────────────────────────────────


def test_proxy_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VKT_PROXY", "http://proxy.example.test:9090")
    assert Bot(token="t", api_url=API_URL).proxy == "http://proxy.example.test:9090"


def test_explicit_proxy_wins_over_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VKT_PROXY", "http://env-proxy:1")
    assert Bot(token="t", api_url=API_URL, proxy="http://explicit:2").proxy == "http://explicit:2"


def test_no_proxy_without_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VKT_PROXY", raising=False)
    assert Bot(token="t", api_url=API_URL).proxy is None
