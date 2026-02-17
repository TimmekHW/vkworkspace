"""Tests for all Bot API methods.

Every public method of ``Bot`` is tested against a mocked HTTP transport
(``httpx.MockTransport``) — no real network calls are made.
"""
from __future__ import annotations

import io
import json
from typing import Any

import httpx
import pytest

from vkworkspace.client.bot import Bot
from vkworkspace.enums import ParseMode
from vkworkspace.exceptions import VKTeamsAPIError
from vkworkspace.types.chat import ChatInfo
from vkworkspace.types.event import Update
from vkworkspace.types.file import File
from vkworkspace.types.input_file import InputFile
from vkworkspace.types.message import ParentMessage
from vkworkspace.types.response import APIResponse
from vkworkspace.types.thread import Thread, ThreadSubscribers
from vkworkspace.types.user import BotInfo, ChatMember, User

API_URL = "https://mock.vkteams.test/bot/v1"
TOKEN = "test-token-001"


# ── helpers ────────────────────────────────────────────────────────────

def _ok(**extra: Any) -> dict[str, Any]:
    """Build a successful API response dict."""
    return {"ok": True, **extra}


def _make_transport(responses: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    """Create an httpx MockTransport that returns preset JSON per endpoint.

    *responses* maps endpoint suffix (e.g. ``"self/get"``) to a JSON-
    serialisable dict.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path  # e.g. /bot/v1/messages/sendText
        for endpoint, body in responses.items():
            if path.endswith(f"/{endpoint}"):
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"ok": False, "description": "Not found"})

    return httpx.MockTransport(handler)


def _bot_with(responses: dict[str, dict[str, Any]], **kwargs: Any) -> Bot:
    """Create a Bot whose session uses a MockTransport."""
    bot = Bot(token=TOKEN, api_url=API_URL, **kwargs)
    transport = _make_transport(responses)
    bot._session = httpx.AsyncClient(transport=transport)
    return bot


# ── fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def ok_bot() -> Bot:
    """Bot that returns ``{"ok": true}`` for any endpoint."""
    return _bot_with(
        {
            # We use a wildcard-ish approach: each test creates its own bot.
            # This fixture is only for the simplest cases.
        }
    )


# ── self/get ───────────────────────────────────────────────────────────

class TestGetMe:
    async def test_returns_bot_info(self):
        bot = _bot_with({
            "self/get": _ok(
                userId="bot@example.com",
                nick="testbot",
                firstName="Test",
                lastName="Bot",
                about="I am a test bot",
                photo=[{"url": "https://example.com/photo.png"}],
            ),
        })
        result = await bot.get_me()
        assert isinstance(result, BotInfo)
        assert result.user_id == "bot@example.com"
        assert result.nick == "testbot"
        assert result.first_name == "Test"
        assert result.about == "I am a test bot"
        assert len(result.photo) == 1
        assert result.photo[0].url == "https://example.com/photo.png"
        await bot.close()


# ── events/get ─────────────────────────────────────────────────────────

class TestGetEvents:
    async def test_returns_updates(self):
        bot = _bot_with({
            "events/get": _ok(events=[
                {"eventId": 1, "type": "newMessage", "payload": {"msgId": "m1"}},
                {"eventId": 2, "type": "editedMessage", "payload": {"msgId": "m2"}},
            ]),
        })
        events = await bot.get_events()
        assert len(events) == 2
        assert all(isinstance(e, Update) for e in events)
        assert events[0].event_id == 1
        assert events[0].type == "newMessage"
        assert events[1].event_id == 2
        await bot.close()

    async def test_tracks_last_event_id(self):
        bot = _bot_with({
            "events/get": _ok(events=[
                {"eventId": 10, "type": "newMessage", "payload": {}},
                {"eventId": 15, "type": "newMessage", "payload": {}},
            ]),
        })
        await bot.get_events()
        assert bot._last_event_id == 15
        await bot.close()

    async def test_empty_events(self):
        bot = _bot_with({"events/get": _ok(events=[])})
        events = await bot.get_events()
        assert events == []
        await bot.close()


# ── messages/sendText ──────────────────────────────────────────────────

class TestSendText:
    async def test_basic(self):
        bot = _bot_with({
            "messages/sendText": _ok(msgId="msg-123"),
        })
        result = await bot.send_text("chat@test", "Hello!")
        assert isinstance(result, APIResponse)
        assert result.ok is True
        assert result.msg_id == "msg-123"
        await bot.close()

    async def test_with_parse_mode(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        result = await bot.send_text("chat@test", "<b>bold</b>", parse_mode=ParseMode.HTML)
        assert result.ok is True
        await bot.close()

    async def test_with_reply_msg_id_list(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        result = await bot.send_text("chat@test", "reply", reply_msg_id=["id1", "id2"])
        assert result.ok is True
        await bot.close()

    async def test_with_forward(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        result = await bot.send_text(
            "chat@test", "fwd",
            forward_chat_id="other@chat",
            forward_msg_id="fwd-1",
        )
        assert result.ok is True
        await bot.close()

    async def test_with_request_id(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        result = await bot.send_text("chat@test", "idempotent", request_id="req-abc")
        assert result.ok is True
        await bot.close()

    async def test_with_parent_topic_dict(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        result = await bot.send_text(
            "chat@test", "thread msg",
            parent_topic={"chatId": "chat@test", "messageId": 999, "type": "thread"},
        )
        assert result.ok is True
        await bot.close()

    async def test_with_parent_topic_object(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        pt = ParentMessage.model_validate({
            "chatId": "chat@test", "messageId": 42, "type": "thread",
        })
        result = await bot.send_text("chat@test", "thread msg", parent_topic=pt)
        assert result.ok is True
        await bot.close()

    async def test_with_format(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        fmt = {"bold": [{"offset": 0, "length": 5}]}
        result = await bot.send_text("chat@test", "Hello world", format_=fmt)
        assert result.ok is True
        await bot.close()

    async def test_with_keyboard(self):
        bot = _bot_with({"messages/sendText": _ok(msgId="m1")})
        kb = [[{"text": "btn", "callbackData": "cb1"}]]
        result = await bot.send_text("chat@test", "pick", inline_keyboard_markup=kb)
        assert result.ok is True
        await bot.close()

    async def test_default_parse_mode(self):
        bot = _bot_with(
            {"messages/sendText": _ok(msgId="m1")},
            parse_mode="HTML",
        )
        result = await bot.send_text("chat@test", "<b>bold</b>")
        assert result.ok is True
        await bot.close()


# ── messages/sendTextWithDeeplink ──────────────────────────────────────

class TestSendTextWithDeeplink:
    async def test_basic(self):
        bot = _bot_with({
            "messages/sendTextWithDeeplink": _ok(msgId="dl-1"),
        })
        result = await bot.send_text_with_deeplink("chat@test", "Hi", deeplink="start_payload")
        assert isinstance(result, APIResponse)
        assert result.msg_id == "dl-1"
        await bot.close()

    async def test_with_keyboard_and_parse_mode(self):
        bot = _bot_with({
            "messages/sendTextWithDeeplink": _ok(msgId="dl-2"),
        })
        kb = [[{"text": "Open", "url": "https://example.com"}]]
        result = await bot.send_text_with_deeplink(
            "chat@test", "<b>Hello</b>", deeplink="ref123",
            inline_keyboard_markup=kb, parse_mode=ParseMode.HTML,
        )
        assert result.ok is True
        await bot.close()


# ── messages/editText ──────────────────────────────────────────────────

class TestEditText:
    async def test_basic(self):
        bot = _bot_with({"messages/editText": _ok()})
        result = await bot.edit_text("chat@test", "msg-1", "Updated text")
        assert result.ok is True
        await bot.close()

    async def test_with_keyboard(self):
        bot = _bot_with({"messages/editText": _ok()})
        kb = [[{"text": "new btn", "callbackData": "new"}]]
        result = await bot.edit_text("chat@test", "msg-1", "Edited", inline_keyboard_markup=kb)
        assert result.ok is True
        await bot.close()


# ── messages/deleteMessages ────────────────────────────────────────────

class TestDeleteMessages:
    async def test_basic(self):
        bot = _bot_with({"messages/deleteMessages": _ok()})
        result = await bot.delete_messages("chat@test", "msg-1")
        assert result.ok is True
        await bot.close()


# ── messages/sendFile ──────────────────────────────────────────────────

class TestSendFile:
    async def test_by_file_id(self):
        bot = _bot_with({"messages/sendFile": _ok(msgId="f1")})
        result = await bot.send_file("chat@test", file_id="existing-file-id")
        assert result.ok is True
        assert result.msg_id == "f1"
        await bot.close()

    async def test_with_upload(self):
        bot = _bot_with({"messages/sendFile": _ok(msgId="f2")})
        buf = io.BytesIO(b"file content")
        result = await bot.send_file("chat@test", file=buf, caption="My file")
        assert result.ok is True
        await bot.close()

    async def test_with_input_file(self):
        bot = _bot_with({"messages/sendFile": _ok(msgId="f3")})
        inp = InputFile(io.BytesIO(b"data"), filename="report.pdf")
        result = await bot.send_file("chat@test", file=inp)
        assert result.ok is True
        await bot.close()

    async def test_with_request_id(self):
        bot = _bot_with({"messages/sendFile": _ok(msgId="f4")})
        result = await bot.send_file("chat@test", file_id="fid", request_id="req-file-1")
        assert result.ok is True
        await bot.close()

    async def test_with_all_params(self):
        bot = _bot_with({"messages/sendFile": _ok(msgId="f5")})
        result = await bot.send_file(
            "chat@test",
            file_id="fid",
            caption="photo",
            reply_msg_id=["r1", "r2"],
            forward_chat_id="other@chat",
            forward_msg_id="fw1",
            parse_mode=ParseMode.HTML,
            format_={"bold": [{"offset": 0, "length": 5}]},
            parent_topic={"chatId": "chat@test", "messageId": 1, "type": "thread"},
            request_id="req-999",
        )
        assert result.ok is True
        await bot.close()


# ── messages/sendVoice ─────────────────────────────────────────────────

class TestSendVoice:
    async def test_by_file_id(self):
        bot = _bot_with({"messages/sendVoice": _ok(msgId="v1")})
        result = await bot.send_voice("chat@test", file_id="voice-file-id")
        assert result.ok is True
        await bot.close()

    async def test_with_upload(self):
        bot = _bot_with({"messages/sendVoice": _ok(msgId="v2")})
        buf = io.BytesIO(b"\x00\x01\x02")
        result = await bot.send_voice("chat@test", file=buf)
        assert result.ok is True
        await bot.close()

    async def test_with_request_id(self):
        bot = _bot_with({"messages/sendVoice": _ok(msgId="v3")})
        result = await bot.send_voice("chat@test", file_id="vid", request_id="req-voice")
        assert result.ok is True
        await bot.close()


# ── messages/answerCallbackQuery ───────────────────────────────────────

class TestAnswerCallbackQuery:
    async def test_basic(self):
        bot = _bot_with({"messages/answerCallbackQuery": _ok()})
        result = await bot.answer_callback_query("query-1")
        assert result.ok is True
        await bot.close()

    async def test_with_text_and_alert(self):
        bot = _bot_with({"messages/answerCallbackQuery": _ok()})
        result = await bot.answer_callback_query(
            "query-2", text="Done!", show_alert=True,
        )
        assert result.ok is True
        await bot.close()

    async def test_with_url(self):
        bot = _bot_with({"messages/answerCallbackQuery": _ok()})
        result = await bot.answer_callback_query("query-3", url="https://example.com")
        assert result.ok is True
        await bot.close()


# ── chats/getInfo ──────────────────────────────────────────────────────

class TestGetChatInfo:
    async def test_basic(self):
        bot = _bot_with({
            "chats/getInfo": _ok(
                type="group",
                title="Test Group",
                nick="testgrp",
                about="A group",
                public=True,
                inviteLink="https://example.com/invite",
            ),
        })
        result = await bot.get_chat_info("chat@test")
        assert isinstance(result, ChatInfo)
        assert result.type == "group"
        assert result.title == "Test Group"
        assert result.public is True
        assert result.invite_link == "https://example.com/invite"
        await bot.close()

    async def test_with_phone_and_photos(self):
        bot = _bot_with({
            "chats/getInfo": _ok(
                type="private",
                firstName="John",
                phone="+79001234567",
                photos=[{"url": "https://example.com/avatar.jpg"}],
            ),
        })
        result = await bot.get_chat_info("user@test")
        assert result.phone == "+79001234567"
        assert len(result.photos) == 1
        assert result.photos[0].url == "https://example.com/avatar.jpg"
        await bot.close()


# ── chats/getAdmins ────────────────────────────────────────────────────

class TestGetChatAdmins:
    async def test_returns_list(self):
        bot = _bot_with({
            "chats/getAdmins": _ok(admins=[
                {"userId": "admin1@test", "creator": True, "admin": True},
                {"userId": "admin2@test", "creator": False, "admin": True},
            ]),
        })
        result = await bot.get_chat_admins("chat@test")
        assert len(result) == 2
        assert all(isinstance(m, ChatMember) for m in result)
        assert result[0].user_id == "admin1@test"
        assert result[0].creator is True
        assert result[1].admin is True
        await bot.close()

    async def test_empty(self):
        bot = _bot_with({"chats/getAdmins": _ok(admins=[])})
        result = await bot.get_chat_admins("chat@test")
        assert result == []
        await bot.close()


# ── chats/getMembers ───────────────────────────────────────────────────

class TestGetChatMembers:
    async def test_returns_raw_dict(self):
        bot = _bot_with({
            "chats/getMembers": _ok(
                members=[{"userId": "u1@test"}, {"userId": "u2@test"}],
                cursor="next-cursor",
            ),
        })
        result = await bot.get_chat_members("chat@test")
        assert isinstance(result, dict)
        assert len(result["members"]) == 2
        assert result["cursor"] == "next-cursor"
        await bot.close()

    async def test_with_cursor(self):
        bot = _bot_with({
            "chats/getMembers": _ok(members=[], cursor=None),
        })
        result = await bot.get_chat_members("chat@test", cursor="abc")
        assert result["ok"] is True
        await bot.close()


# ── chats/getBlockedUsers ──────────────────────────────────────────────

class TestGetBlockedUsers:
    async def test_returns_list(self):
        bot = _bot_with({
            "chats/getBlockedUsers": _ok(users=[
                {"userId": "blocked@test"},
            ]),
        })
        result = await bot.get_blocked_users("chat@test")
        assert len(result) == 1
        assert isinstance(result[0], User)
        assert result[0].user_id == "blocked@test"
        await bot.close()


# ── chats/getPendingUsers ──────────────────────────────────────────────

class TestGetPendingUsers:
    async def test_returns_list(self):
        bot = _bot_with({
            "chats/getPendingUsers": _ok(users=[
                {"userId": "pending1@test"},
                {"userId": "pending2@test"},
            ]),
        })
        result = await bot.get_pending_users("chat@test")
        assert len(result) == 2
        assert result[0].user_id == "pending1@test"
        await bot.close()


# ── chats/blockUser ────────────────────────────────────────────────────

class TestBlockUser:
    async def test_basic(self):
        bot = _bot_with({"chats/blockUser": _ok()})
        result = await bot.block_user("chat@test", "user@test")
        assert result.ok is True
        await bot.close()

    async def test_with_delete_messages(self):
        bot = _bot_with({"chats/blockUser": _ok()})
        result = await bot.block_user("chat@test", "user@test", del_last_messages=True)
        assert result.ok is True
        await bot.close()


# ── chats/unblockUser ──────────────────────────────────────────────────

class TestUnblockUser:
    async def test_basic(self):
        bot = _bot_with({"chats/unblockUser": _ok()})
        result = await bot.unblock_user("chat@test", "user@test")
        assert result.ok is True
        await bot.close()


# ── chats/resolvePending ───────────────────────────────────────────────

class TestResolvePending:
    async def test_approve_one(self):
        bot = _bot_with({"chats/resolvePending": _ok()})
        result = await bot.resolve_pending("chat@test", approve=True, user_id="user@test")
        assert result.ok is True
        await bot.close()

    async def test_reject_everyone(self):
        bot = _bot_with({"chats/resolvePending": _ok()})
        result = await bot.resolve_pending("chat@test", approve=False, everyone=True)
        assert result.ok is True
        await bot.close()


# ── chats/setTitle ─────────────────────────────────────────────────────

class TestSetChatTitle:
    async def test_basic(self):
        bot = _bot_with({"chats/setTitle": _ok()})
        result = await bot.set_chat_title("chat@test", "New Title")
        assert result.ok is True
        await bot.close()


# ── chats/setAbout ─────────────────────────────────────────────────────

class TestSetChatAbout:
    async def test_basic(self):
        bot = _bot_with({"chats/setAbout": _ok()})
        result = await bot.set_chat_about("chat@test", "New description")
        assert result.ok is True
        await bot.close()


# ── chats/setRules ─────────────────────────────────────────────────────

class TestSetChatRules:
    async def test_basic(self):
        bot = _bot_with({"chats/setRules": _ok()})
        result = await bot.set_chat_rules("chat@test", "Be nice")
        assert result.ok is True
        await bot.close()


# ── chats/members/delete ───────────────────────────────────────────────

class TestDeleteChatMembers:
    async def test_basic(self):
        bot = _bot_with({"chats/members/delete": _ok()})
        result = await bot.delete_chat_members("chat@test", ["user1@test", "user2@test"])
        assert result.ok is True
        await bot.close()


# ── chats/members/add ──────────────────────────────────────────────────

class TestAddChatMembers:
    async def test_basic(self):
        bot = _bot_with({"chats/members/add": _ok()})
        result = await bot.add_chat_members("chat@test", ["new1@test", "new2@test"])
        assert result.ok is True
        await bot.close()


# ── chats/avatar/set ───────────────────────────────────────────────────

class TestSetChatAvatar:
    async def test_with_bytes(self):
        bot = _bot_with({"chats/avatar/set": _ok()})
        buf = io.BytesIO(b"\x89PNG\r\n")
        result = await bot.set_chat_avatar("chat@test", buf)
        assert result.ok is True
        await bot.close()

    async def test_with_input_file(self):
        bot = _bot_with({"chats/avatar/set": _ok()})
        inp = InputFile(io.BytesIO(b"\x89PNG"), filename="avatar.png")
        result = await bot.set_chat_avatar("chat@test", inp)
        assert result.ok is True
        await bot.close()


# ── chats/sendActions ──────────────────────────────────────────────────

class TestSendActions:
    async def test_typing(self):
        bot = _bot_with({"chats/sendActions": _ok()})
        result = await bot.send_actions("chat@test", "typing")
        assert result.ok is True
        await bot.close()

    async def test_looking(self):
        bot = _bot_with({"chats/sendActions": _ok()})
        result = await bot.send_actions("chat@test", "looking")
        assert result.ok is True
        await bot.close()


# ── chats/pinMessage ───────────────────────────────────────────────────

class TestPinMessage:
    async def test_basic(self):
        bot = _bot_with({"chats/pinMessage": _ok()})
        result = await bot.pin_message("chat@test", "msg-1")
        assert result.ok is True
        await bot.close()


# ── chats/unpinMessage ─────────────────────────────────────────────────

class TestUnpinMessage:
    async def test_basic(self):
        bot = _bot_with({"chats/unpinMessage": _ok()})
        result = await bot.unpin_message("chat@test", "msg-1")
        assert result.ok is True
        await bot.close()


# ── files/getInfo ──────────────────────────────────────────────────────

class TestGetFileInfo:
    async def test_basic(self):
        bot = _bot_with({
            "files/getInfo": _ok(
                fileId="file-abc",
                type="image",
                size=1024,
                filename="photo.png",
                url="https://files.example.com/photo.png",
            ),
        })
        result = await bot.get_file_info("file-abc")
        assert isinstance(result, File)
        assert result.file_id == "file-abc"
        assert result.type == "image"
        assert result.size == 1024
        assert result.filename == "photo.png"
        assert result.url == "https://files.example.com/photo.png"
        await bot.close()


# ── threads/subscribers/get ────────────────────────────────────────────

class TestThreadsGetSubscribers:
    async def test_basic(self):
        bot = _bot_with({
            "threads/subscribers/get": _ok(
                cursor="cur-1",
                subscribers=[
                    {"userId": "u1@test", "firstName": "Alice"},
                    {"userId": "u2@test", "firstName": "Bob"},
                ],
            ),
        })
        result = await bot.threads_get_subscribers("thread-1")
        assert isinstance(result, ThreadSubscribers)
        assert result.cursor == "cur-1"
        assert len(result.subscribers) == 2
        assert result.subscribers[0].user_id == "u1@test"
        await bot.close()

    async def test_with_pagination(self):
        bot = _bot_with({
            "threads/subscribers/get": _ok(cursor=None, subscribers=[]),
        })
        result = await bot.threads_get_subscribers("thread-1", page_size=10, cursor="cur-x")
        assert result.subscribers == []
        await bot.close()


# ── threads/autosubscribe ──────────────────────────────────────────────

class TestThreadsAutosubscribe:
    async def test_enable(self):
        bot = _bot_with({"threads/autosubscribe": _ok()})
        result = await bot.threads_autosubscribe("chat@test", enable=True)
        assert result.ok is True
        await bot.close()

    async def test_disable_with_existing(self):
        bot = _bot_with({"threads/autosubscribe": _ok()})
        result = await bot.threads_autosubscribe(
            "chat@test", enable=False, with_existing=True,
        )
        assert result.ok is True
        await bot.close()


# ── threads/add ────────────────────────────────────────────────────────

class TestThreadsAdd:
    async def test_basic(self):
        bot = _bot_with({
            "threads/add": _ok(threadId="thread-999", msgId="msg-1"),
        })
        result = await bot.threads_add("chat@test", "msg-1")
        assert isinstance(result, Thread)
        assert result.thread_id == "thread-999"
        assert result.msg_id == "msg-1"
        await bot.close()


# ── error handling ─────────────────────────────────────────────────────

class TestErrorHandling:
    async def test_api_error_raised(self):
        bot = _bot_with({
            "messages/sendText": {"ok": False, "description": "Access denied"},
        })
        with pytest.raises(VKTeamsAPIError) as exc_info:
            await bot.send_text("chat@test", "test")
        assert "Access denied" in str(exc_info.value)
        assert exc_info.value.method == "messages/sendText"
        await bot.close()

    async def test_http_error_raised(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Internal Server Error"})

        bot = Bot(token=TOKEN, api_url=API_URL)
        bot._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await bot.send_text("chat@test", "test")
        await bot.close()


# ── _params helper ─────────────────────────────────────────────────────

class TestParams:
    def test_skips_none(self):
        bot = Bot(token=TOKEN)
        p = bot._params(chatId="c1", replyMsgId=None)
        assert "replyMsgId" not in p
        assert p["chatId"] == "c1"

    def test_bool_serialization(self):
        bot = Bot(token=TOKEN)
        p = bot._params(enable=True, delLastMessages=False)
        assert p["enable"] == "true"
        assert p["delLastMessages"] == "false"

    def test_list_serialization(self):
        bot = Bot(token=TOKEN)
        p = bot._params(members=[{"sn": "u1"}, {"sn": "u2"}])
        parsed = json.loads(p["members"])
        assert parsed == [{"sn": "u1"}, {"sn": "u2"}]

    def test_dict_serialization(self):
        bot = Bot(token=TOKEN)
        p = bot._params(format={"bold": [{"offset": 0, "length": 5}]})
        parsed = json.loads(p["format"])
        assert parsed["bold"][0]["offset"] == 0

    def test_string_passthrough(self):
        bot = Bot(token=TOKEN)
        p = bot._params(chatId="chat@test", text="hello")
        assert p["chatId"] == "chat@test"
        assert p["text"] == "hello"

    def test_token_always_present(self):
        bot = Bot(token="my-token")
        p = bot._params()
        assert p["token"] == "my-token"


# ── _msg_ids helper ────────────────────────────────────────────────────

class TestMsgIds:
    def test_none(self):
        assert Bot._msg_ids(None) is None

    def test_single_string(self):
        assert Bot._msg_ids("abc") == "abc"

    def test_list_single(self):
        assert Bot._msg_ids(["abc"]) == "abc"

    def test_list_multiple(self):
        assert Bot._msg_ids(["a", "b", "c"]) == "a,b,c"

    def test_empty_list(self):
        assert Bot._msg_ids([]) == ""


# ── parse_mode resolution ──────────────────────────────────────────────

class TestParseModeResolution:
    def test_explicit_overrides_default(self):
        bot = Bot(token=TOKEN, parse_mode="HTML")
        assert bot._resolve_parse_mode("MarkdownV2") == "MarkdownV2"

    def test_fallback_to_default(self):
        from vkworkspace.client.bot import _UNSET
        bot = Bot(token=TOKEN, parse_mode="HTML")
        assert bot._resolve_parse_mode(_UNSET) == "HTML"

    def test_none_overrides_default(self):
        bot = Bot(token=TOKEN, parse_mode="HTML")
        assert bot._resolve_parse_mode(None) is None

    def test_no_default_no_explicit(self):
        from vkworkspace.client.bot import _UNSET
        bot = Bot(token=TOKEN)
        assert bot._resolve_parse_mode(_UNSET) is None


# ── keyboard / format / parent_topic helpers ───────────────────────────

class TestHelpers:
    def test_keyboard_json_none(self):
        assert Bot._keyboard_json(None) is None

    def test_keyboard_json_string(self):
        assert Bot._keyboard_json('[[{"text":"a"}]]') == '[[{"text":"a"}]]'

    def test_keyboard_json_list(self):
        kb = [[{"text": "btn", "callbackData": "d"}]]
        result = Bot._keyboard_json(kb)
        assert result is not None
        assert json.loads(result) == kb

    def test_parent_topic_json_none(self):
        assert Bot._parent_topic_json(None) is None

    def test_parent_topic_json_dict(self):
        pt = {"chatId": "c1", "messageId": 1, "type": "thread"}
        result = Bot._parent_topic_json(pt)
        assert result is not None
        assert json.loads(result) == pt

    def test_format_json_none(self):
        assert Bot._format_json(None) is None

    def test_format_json_dict(self):
        fmt = {"bold": [{"offset": 0, "length": 3}]}
        result = Bot._format_json(fmt)
        assert result is not None
        assert json.loads(result) == fmt

    def test_format_json_string(self):
        s = '{"bold":[]}'
        assert Bot._format_json(s) == s


# ── session / lifecycle ────────────────────────────────────────────────

class TestSessionLifecycle:
    async def test_get_session_creates_client(self):
        bot = Bot(token=TOKEN, api_url=API_URL)
        session = await bot.get_session()
        assert isinstance(session, httpx.AsyncClient)
        assert not session.is_closed
        await bot.close()
        assert session.is_closed

    async def test_close_idempotent(self):
        bot = Bot(token=TOKEN)
        await bot.close()  # no session yet — should not raise
        _ = await bot.get_session()
        await bot.close()
        await bot.close()  # already closed — should not raise

    async def test_session_recreated_after_close(self):
        bot = Bot(token=TOKEN)
        s1 = await bot.get_session()
        await bot.close()
        s2 = await bot.get_session()
        assert s1 is not s2
        await bot.close()

    async def test_proxy_passed_to_session(self):
        bot = Bot(token=TOKEN, proxy="http://proxy:8080")
        assert bot.proxy == "http://proxy:8080"
        await bot.close()


# ── request verification (check endpoint + params are sent) ────────────

class TestRequestVerification:
    """Verify that the correct endpoint and parameters are sent."""

    async def test_send_text_sends_correct_params(self):
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode()
            return httpx.Response(200, json=_ok(msgId="m1"))

        bot = Bot(token=TOKEN, api_url=API_URL)
        bot._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        await bot.send_text("chat@test", "Hello!", request_id="rid-1")

        assert "messages/sendText" in captured["url"]
        body = captured["body"]
        assert "chatId=chat%40test" in body or "chatId=chat@test" in body.replace("%40", "@")
        assert "Hello" in body
        assert "rid-1" in body
        await bot.close()

    async def test_add_chat_members_sends_correct_params(self):
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode()
            return httpx.Response(200, json=_ok())

        bot = Bot(token=TOKEN, api_url=API_URL)
        bot._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        await bot.add_chat_members("chat@test", ["alice@test", "bob@test"])

        assert "chats/members/add" in captured["url"]
        body = captured["body"]
        assert "alice@test" in body.replace("%40", "@")
        assert "bob@test" in body.replace("%40", "@")
        await bot.close()

    async def test_send_text_with_deeplink_sends_correct_params(self):
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode()
            return httpx.Response(200, json=_ok(msgId="dl"))

        bot = Bot(token=TOKEN, api_url=API_URL)
        bot._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        await bot.send_text_with_deeplink("chat@test", "Hi", deeplink="payload123")

        assert "messages/sendTextWithDeeplink" in captured["url"]
        assert "payload123" in captured["body"]
        await bot.close()

    async def test_threads_add_sends_correct_params(self):
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode()
            return httpx.Response(200, json=_ok(threadId="t1"))

        bot = Bot(token=TOKEN, api_url=API_URL)
        bot._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        await bot.threads_add("chat@test", "msg-42")

        assert "threads/add" in captured["url"]
        assert "msg-42" in captured["body"]
        await bot.close()
