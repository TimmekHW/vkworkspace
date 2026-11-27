"""The path of one Bot API call: request middlewares, library exception types,
and the resend after «Format error».

No real network: clients run on ``httpx2.MockTransport``.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any
from urllib.parse import parse_qs

import httpx2
import pytest

from vkworkspace import Bot
from vkworkspace.exceptions import (
    FileDownloadError,
    VKTeamsAPIError,
    VKTeamsHTTPError,
    VKTeamsNetworkError,
    VKWorkspaceError,
)
from vkworkspace.formatting import from_markdown
from vkworkspace.utils.text import Bold, Code, Italic, Text

API_URL = "https://mock.vkteams.test/bot/v1"
TOKEN = "test-token-001"
OK = {"ok": True, "msgId": "m1"}
FORMAT_ERROR = {"ok": False, "description": "Format error"}


def _bot(handler: Any, **kwargs: Any) -> Bot:
    bot = Bot(token=TOKEN, api_url=API_URL, **kwargs)
    bot._session = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return bot


def _form(request: httpx2.Request) -> dict[str, str]:
    """Fields of a urlencoded or multipart request body (text fields only)."""
    content_type = request.headers.get("content-type", "")
    body = request.read()
    if "multipart/form-data" not in content_type:
        return {k: v[0] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}
    fields: dict[str, str] = {}
    boundary = content_type.split("boundary=")[1].encode()
    for part in body.split(b"--" + boundary):
        head, _, value = part.partition(b"\r\n\r\n")
        if b'name="' not in head or b"filename=" in head:
            continue
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        fields[name] = value.rstrip(b"\r\n").decode()
    return fields


# ── exception types ────────────────────────────────────────────────────


class TestExceptions:
    async def test_transport_failure_is_a_network_error(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("", request=request)

        bot = _bot(handler, retry_on_5xx=None)
        with pytest.raises(VKTeamsNetworkError) as info:
            await bot.send_text("c@x", "hi")
        err = info.value
        assert isinstance(err, VKWorkspaceError)
        assert err.method == "messages/sendText"
        assert err.message == "ReadTimeout"
        assert isinstance(err.original, httpx2.ReadTimeout)
        assert str(err) == "Network error in messages/sendText: ReadTimeout"
        assert err.__cause__ is err.original
        await bot.close()

    async def test_network_error_carries_the_http_client_error(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("boom", request=request)

        bot = _bot(handler, retry_on_5xx=None)
        with pytest.raises(VKTeamsNetworkError) as info:
            await bot.send_text("c@x", "hi")
        err = info.value
        assert not isinstance(err, httpx2.HTTPError)  # one type to catch: the library's
        assert isinstance(err.original, httpx2.ConnectError)
        assert err.original.request.url.path.endswith("/messages/sendText")
        assert err.message == "ConnectError: boom"
        await bot.close()

    async def test_http_status_is_an_http_error(self):
        bot = _bot(lambda request: httpx2.Response(403), retry_on_5xx=None)
        with pytest.raises(VKTeamsHTTPError) as info:
            await bot.send_text("c@x", "hi")
        err = info.value
        assert err.status_code == 403
        assert err.method == "messages/sendText"
        assert err.message == "HTTP 403"
        assert str(err) == "HTTP error in messages/sendText: HTTP 403"
        assert isinstance(err.original, httpx2.HTTPStatusError)
        assert err.original.response.status_code == 403
        assert not isinstance(err, VKTeamsNetworkError)
        await bot.close()

    async def test_api_error_is_unchanged(self):
        bot = _bot(
            lambda request: httpx2.Response(200, json={"ok": False, "description": "Nope"}),
        )
        with pytest.raises(VKTeamsAPIError, match="API error in messages/sendText: Nope") as info:
            await bot.send_text("c@x", "hi")
        assert type(info.value) is VKTeamsAPIError
        await bot.close()

    async def test_long_poll_reports_http_errors(self):
        for status in (404, 502, 504):
            bot = _bot(lambda request, status=status: httpx2.Response(status), retry_on_5xx=None)
            with pytest.raises(VKTeamsHTTPError) as info:
                await bot.get_events()
            assert info.value.status_code == status
            await bot.close()

    async def test_answer_that_is_not_bot_api_json_is_a_network_error(self):
        """A page of a proxy with HTTP 200, a JSON list, a broken encoding."""

        def broken_encoding(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.DecodingError("incorrect header check")

        answers = [
            lambda request: httpx2.Response(200, html="<html>Sign in to the network</html>"),
            lambda request: httpx2.Response(200, json=[1, 2]),
            broken_encoding,
        ]
        for answer in answers:
            bot = _bot(answer)
            with pytest.raises(VKTeamsNetworkError):
                await bot.get_me()
            await bot.close()
        bot = _bot(lambda request: httpx2.Response(200, html="<html>Sign in</html>"))
        with pytest.raises(VKTeamsNetworkError, match=r"not Bot API JSON.*text/html.*Sign in"):
            await bot.get_me()
        await bot.close()

    async def test_file_opened_for_an_upload_is_closed(self, tmp_path, monkeypatch):
        from vkworkspace.types.input_file import InputFile

        path = tmp_path / "report.txt"
        path.write_bytes(b"data")
        opened: list[Any] = []
        read = InputFile.read

        def spy(self: InputFile) -> Any:
            result = read(self)
            opened.append(result[1])
            return result

        monkeypatch.setattr(InputFile, "read", spy)
        bot = _bot(lambda request: httpx2.Response(200, json={"ok": True, "msgId": "m1"}))
        await bot.send_file("c@x", file=InputFile(path))
        assert opened[0].closed
        mine = io.BytesIO(b"data")
        await bot.send_file("c@x", file=mine)
        assert not mine.closed  # a stream of the caller stays open
        await bot.close()

    async def test_exception_from_a_response_hook_passes_through(self):
        """An application's own exception raised inside a client hook stays itself."""

        class OutcomeUnknown(Exception):
            pass

        async def reject(response: httpx2.Response) -> None:
            if response.status_code == 504:
                raise OutcomeUnknown

        calls = 0

        def handler(request: httpx2.Request) -> httpx2.Response:
            nonlocal calls
            calls += 1
            return httpx2.Response(504)

        bot = _bot(handler)
        (await bot.get_session()).event_hooks["response"].append(reject)
        with pytest.raises(OutcomeUnknown):
            await bot.send_text("c@x", "hi")
        assert calls == 1  # not retried: the application decided
        await bot.close()

    async def test_download_error_names_the_http_client_error(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("refused", request=request)

        bot = _bot(handler, retry_on_5xx=1)
        with pytest.raises(FileDownloadError, match="ConnectError: refused"):
            await bot.download_file_by_url("https://files.test/get/abc")
        await bot.close()


# ── request middlewares ────────────────────────────────────────────────


class TestRequestMiddlewares:
    async def test_middlewares_wrap_the_call_in_registration_order(self):
        bot = _bot(lambda request: httpx2.Response(200, json=OK))
        trace: list[str] = []

        @bot.request_middleware
        async def outer(make_request, endpoint, params, files):
            trace.append(f"outer> {endpoint}")
            data = await make_request(endpoint, params, files)
            trace.append("outer<")
            return data

        @bot.request_middleware
        async def inner(make_request, endpoint, params, files):
            trace.append("inner>")
            data = await make_request(endpoint, params, files)
            trace.append("inner<")
            return data

        resp = await bot.send_text("c@x", "hi")
        assert resp.msg_id == "m1"
        assert trace == ["outer> messages/sendText", "inner>", "inner<", "outer<"]
        assert bot.request_middlewares == [outer, inner]
        await bot.close()

    async def test_middleware_can_change_the_request_and_the_answer(self):
        seen: dict[str, str] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.update(_form(request))
            return httpx2.Response(200, json=OK)

        bot = _bot(handler)

        @bot.request_middleware
        async def sign(make_request, endpoint, params, files):
            data = await make_request(
                endpoint, {**params, "text": params["text"] + " — bot"}, files
            )
            return {**data, "msgId": "changed"}

        resp = await bot.send_text("c@x", "hi")
        assert seen["text"] == "hi — bot"
        assert resp.msg_id == "changed"
        await bot.close()

    async def test_middleware_sees_one_call_and_library_errors(self):
        calls = 0

        def handler(request: httpx2.Request) -> httpx2.Response:
            nonlocal calls
            calls += 1
            raise httpx2.ConnectError("", request=request)

        bot = _bot(handler, retry_on_5xx=2)
        seen: list[BaseException] = []

        @bot.request_middleware
        async def watch(make_request, endpoint, params, files):
            try:
                return await make_request(endpoint, params, files)
            except VKTeamsNetworkError as exc:
                seen.append(exc)
                return {"ok": True, "msgId": "queued"}

        resp = await bot.send_text("c@x", "hi")
        assert calls == 3  # the built-in retries ran inside one middleware call
        assert len(seen) == 1
        assert resp.msg_id == "queued"
        await bot.close()

    async def test_class_based_middleware(self):
        bot = _bot(lambda request: httpx2.Response(200, json=OK))

        class Counter:
            def __init__(self) -> None:
                self.endpoints: list[str] = []

            async def __call__(self, make_request, endpoint, params, files):
                self.endpoints.append(endpoint)
                return await make_request(endpoint, params, files)

        counter = Counter()
        bot.request_middlewares.append(counter)
        await bot.send_text("c@x", "hi")
        await bot.set_chat_title("c@x", "title")
        assert counter.endpoints == ["messages/sendText", "chats/setTitle"]
        await bot.close()


# ── «Format error» ─────────────────────────────────────────────────────


@pytest.fixture
def sent() -> list[dict[str, str]]:
    return []


def _rejecting(sent: list[dict[str, str]], accept: Any) -> Any:
    """Handler that answers «Format error» until *accept(fields)* is true."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        fields = _form(request)
        sent.append(fields)
        return httpx2.Response(200, json=OK if accept(fields) else FORMAT_ERROR)

    return handler


class TestFormatFallback:
    async def test_html_is_rebuilt_and_resent(self, sent, caplog):
        broken = "<b>Итог: 5 < 10 & растёт<i>дальше</b>"
        bot = _bot(_rejecting(sent, lambda f: f["text"] != broken))
        with caplog.at_level(logging.WARNING, logger="vkworkspace.client.bot"):
            resp = await bot.send_text("c@x", broken, parse_mode="HTML")
        assert resp.msg_id == "m1"
        assert len(sent) == 2
        assert sent[1]["parseMode"] == "HTML"
        assert sent[1]["text"] != broken
        assert "&lt; 10 &amp; растёт" in sent[1]["text"]
        assert sent[1]["text"].count("<b>") == sent[1]["text"].count("</b>")
        assert sent[1]["text"].count("<i>") == sent[1]["text"].count("</i>")
        assert "the message was sent with repaired HTML" in caplog.text
        await bot.close()

    async def test_plain_text_when_repaired_html_is_rejected_too(self, sent, caplog):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        with caplog.at_level(logging.WARNING, logger="vkworkspace.client.bot"):
            await bot.send_text(
                "c@x", '<b>Отчёт</b>: <a href="https://x.test">ссылка</a> <', parse_mode="HTML"
            )
        assert len(sent) == 3
        assert "parseMode" not in sent[2]
        assert sent[2]["text"] == "Отчёт: ссылка (https://x.test) <"
        assert "the message was sent as plain text" in caplog.text
        await bot.close()

    async def test_valid_looking_html_goes_straight_to_plain_text(self, sent):
        """Nothing to repair: the rebuilt HTML equals the original, so it is not sent twice."""
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        await bot.send_text("c@x", "<b>ok</b>", parse_mode="HTML")
        assert [f.get("parseMode") for f in sent] == ["HTML", None]
        assert sent[1]["text"] == "ok"
        await bot.close()

    async def test_markdown_goes_as_plain_text_without_escapes(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        await bot.send_text("c@x", r"Версия 2\.0 \(готово\) *и", parse_mode="MarkdownV2")
        assert len(sent) == 2
        assert sent[1]["text"] == "Версия 2.0 (готово) *и"
        await bot.close()

    async def test_edit_text_is_repaired_too(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        await bot.edit_text("c@x", "42", "<b>x", parse_mode="HTML")
        assert sent[-1]["text"] == "x"
        assert sent[-1]["msgId"] == "42"
        await bot.close()

    async def test_bot_default_parse_mode_is_covered(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f), parse_mode="HTML")
        await bot.send_text("c@x", "a <b>b")
        assert sent[0]["parseMode"] == "HTML"
        assert sent[-1]["text"] == "a b"
        await bot.close()

    async def test_format_offsets_are_dropped(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "format" not in f))
        await bot.send_text("c@x", "hello", format_={"bold": [{"offset": 0, "length": 99}]})
        assert len(sent) == 2
        assert json.loads(sent[0]["format"])["bold"][0]["length"] == 99
        assert sent[1]["text"] == "hello"
        await bot.close()

    async def test_caption_of_a_file_is_repaired(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        await bot.send_file("c@x", file=io.BytesIO(b"data"), caption="<b>Файл", parse_mode="HTML")
        assert sent[-1]["caption"] == "Файл"
        assert "parseMode" not in sent[-1]
        await bot.close()

    async def test_other_fields_are_kept(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        await bot.send_text(
            "c@x",
            "<b>x",
            parse_mode="HTML",
            reply_msg_id="7",
            inline_keyboard_markup=[[{"text": "OK", "callbackData": "ok"}]],
        )
        last = sent[-1]
        assert last["chatId"] == "c@x"
        assert last["replyMsgId"] == "7"
        assert json.loads(last["inlineKeyboardMarkup"])[0][0]["text"] == "OK"
        assert last["token"] == TOKEN
        await bot.close()

    async def test_error_is_raised_when_nothing_helps(self, sent):
        bot = _bot(_rejecting(sent, lambda f: False))
        with pytest.raises(VKTeamsAPIError, match="Format error"):
            await bot.send_text("c@x", "<b>x", parse_mode="HTML")
        assert len(sent) == 3  # as sent, repaired, plain
        await bot.close()

    async def test_plain_message_is_not_resent(self, sent):
        """No markup to drop — e.g. the keyboard is what the server rejects."""
        bot = _bot(_rejecting(sent, lambda f: False))
        with pytest.raises(VKTeamsAPIError, match="Format error"):
            await bot.send_text("c@x", "hello")
        assert len(sent) == 1
        await bot.close()

    async def test_switched_off(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f), format_fallback=False)
        with pytest.raises(VKTeamsAPIError, match="Format error"):
            await bot.send_text("c@x", "<b>x", parse_mode="HTML")
        assert len(sent) == 1
        await bot.close()

    async def test_other_api_errors_are_not_touched(self, sent):
        def handler(request: httpx2.Request) -> httpx2.Response:
            sent.append(_form(request))
            return httpx2.Response(200, json={"ok": False, "description": "Permission denied"})

        bot = _bot(handler)
        with pytest.raises(VKTeamsAPIError, match="Permission denied"):
            await bot.send_text("c@x", "<b>x", parse_mode="HTML")
        assert len(sent) == 1
        await bot.close()

    async def test_error_other_than_format_during_the_resend_is_raised(self, sent):
        def handler(request: httpx2.Request) -> httpx2.Response:
            sent.append(_form(request))
            if len(sent) == 1:
                return httpx2.Response(200, json=FORMAT_ERROR)
            return httpx2.Response(200, json={"ok": False, "description": "Permission denied"})

        bot = _bot(handler)
        with pytest.raises(VKTeamsAPIError, match="Permission denied"):
            await bot.send_text("c@x", "<b>x", parse_mode="HTML")
        assert len(sent) == 2
        await bot.close()


# ── a Text tree instead of a string ─────────────────────────────────────

MARKDOWN = "**Итог:** `x` и [ссылка](https://example.org/a_b)\n\n- пункт 1\n- пункт 2"
PLAIN = "Итог: x и ссылка (https://example.org/a_b)\n\n• пункт 1\n• пункт 2"


class TestTextTree:
    async def test_tree_is_rendered_for_the_parse_mode_of_the_call(self, sent):
        tree = from_markdown(MARKDOWN)
        bot = _bot(_rejecting(sent, lambda f: True))
        await bot.send_text("c@x", tree, parse_mode="MarkdownV2")
        await bot.send_text("c@x", tree, parse_mode="HTML")
        await bot.send_text("c@x", tree, parse_mode=None)
        assert (sent[0]["text"], sent[0]["parseMode"]) == (tree.as_markdown(), "MarkdownV2")
        assert (sent[1]["text"], sent[1]["parseMode"]) == (tree.as_html(), "HTML")
        assert sent[2]["text"] == PLAIN
        assert "parseMode" not in sent[2]
        await bot.close()

    async def test_parse_mode_of_the_bot_and_html_when_none_is_set(self, sent):
        tree = Text("Цена: ", Bold("100"))
        bot = _bot(_rejecting(sent, lambda f: True), parse_mode="MarkdownV2")
        await bot.send_text("c@x", tree)
        assert (sent[0]["text"], sent[0]["parseMode"]) == ("Цена: *100*", "MarkdownV2")
        await bot.close()

        bot = _bot(_rejecting(sent, lambda f: True))
        await bot.send_text("c@x", tree)
        assert (sent[1]["text"], sent[1]["parseMode"]) == ("Цена: <b>100</b>", "HTML")
        await bot.close()

    async def test_rejected_markdown_tree_goes_as_its_plain_text(self, sent, caplog):
        """The plain text comes from the tree: no asterisks, backticks or [text](url)."""
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        with caplog.at_level(logging.WARNING, logger="vkworkspace.client.bot"):
            resp = await bot.send_text("c@x", from_markdown(MARKDOWN), parse_mode="MarkdownV2")
        assert resp.msg_id == "m1"
        assert [f.get("parseMode") for f in sent] == ["MarkdownV2", None]
        assert sent[1]["text"] == PLAIN
        assert "the message was sent as plain text" in caplog.text
        await bot.close()

    async def test_rejected_html_tree_goes_as_its_plain_text(self, sent):
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        await bot.send_text("c@x", from_markdown(MARKDOWN), parse_mode="HTML")
        assert sent[0]["parseMode"] == "HTML"
        assert "parseMode" not in sent[-1]
        assert sent[-1]["text"] == PLAIN
        await bot.close()

    async def test_edit_text_and_caption_take_a_tree(self, sent):
        tree = Text("Отчёт ", Code("v2"))
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))
        await bot.edit_text("c@x", "1", tree, parse_mode="MarkdownV2")
        assert (sent[0]["text"], sent[1]["text"]) == ("Отчёт `v2`", "Отчёт v2")
        await bot.send_file("c@x", file=io.BytesIO(b"data"), caption=tree, parse_mode="MarkdownV2")
        assert (sent[2]["caption"], sent[3]["caption"]) == ("Отчёт `v2`", "Отчёт v2")
        await bot.send_text_with_deeplink("c@x", tree, deeplink="start", parse_mode="HTML")
        assert sent[4]["text"] == "Отчёт <code>v2</code>"
        await bot.close()

    async def test_error_is_raised_when_the_plain_text_is_rejected_too(self, sent):
        bot = _bot(_rejecting(sent, lambda f: False))
        with pytest.raises(VKTeamsAPIError, match="Format error"):
            await bot.send_text("c@x", from_markdown(MARKDOWN), parse_mode="MarkdownV2")
        assert len(sent) == 2
        await bot.close()

    async def test_no_resend_when_the_fallback_is_off_or_the_error_is_another(self, sent):
        bot = _bot(_rejecting(sent, lambda f: False), format_fallback=False)
        with pytest.raises(VKTeamsAPIError, match="Format error"):
            await bot.send_text("c@x", Text(Bold("x")), parse_mode="MarkdownV2")
        assert len(sent) == 1
        await bot.close()

        calls = 0

        def gateway_timeout(request: httpx2.Request) -> httpx2.Response:
            nonlocal calls
            calls += 1
            return httpx2.Response(504)

        bot = _bot(gateway_timeout)
        with pytest.raises(VKTeamsHTTPError):
            await bot.send_text("c@x", Text(Bold("x")), parse_mode="MarkdownV2")
        assert calls == 1
        await bot.close()

    async def test_middleware_sees_one_call_with_the_rendered_string(self, sent):
        seen: list[Any] = []
        bot = _bot(_rejecting(sent, lambda f: "parseMode" not in f))

        @bot.request_middleware
        async def spy(make_request: Any, endpoint: str, params: Any, files: Any) -> Any:
            seen.append((endpoint, params["text"], params.get("parseMode")))
            return await make_request(endpoint, params, files)

        await bot.send_text("c@x", Text("a ", Bold("b")), parse_mode="MarkdownV2")
        assert seen == [("messages/sendText", "a *b*", "MarkdownV2")]
        assert isinstance(seen[0][1], str)
        assert len(sent) == 2
        await bot.close()

    async def test_offset_formatting_cannot_be_combined_with_a_tree(self):
        bot = _bot(lambda request: httpx2.Response(200, json=OK))
        with pytest.raises(ValueError, match="format_"):
            await bot.send_text("c@x", Text("x"), format_={"bold": [{"offset": 0, "length": 1}]})
        await bot.close()

    async def test_message_methods_take_a_tree(self, sent):
        from vkworkspace.types.chat import Chat
        from vkworkspace.types.message import Message

        bot = _bot(_rejecting(sent, lambda f: True), parse_mode="HTML")
        message = Message.model_construct(msg_id="1", chat=Chat(chatId="c@x", type="private"))
        message.set_bot(bot)
        tree = Text("Готово: ", Bold("да"))
        answered = await message.answer(tree)
        replied = await message.reply(tree, parse_mode="MarkdownV2")
        await answered.edit_text(Text(Italic("правка")))
        assert [f["text"] for f in sent] == ["Готово: <b>да</b>", "Готово: *да*", "<i>правка</i>"]
        assert answered.text == replied.text == "Готово: да"
        await bot.close()


# ── every member of a chat ──────────────────────────────────────────────


class TestIterChatMembers:
    async def test_pages_are_followed_until_the_cursor_ends(self):
        pages = {
            None: {"ok": True, "members": [{"userId": "a@x"}, {"userId": "b@x"}], "cursor": "p2"},
            "p2": {
                "ok": True,
                "members": [{"userId": "c@x", "sn": "c", "nick": "bot_c"}],
                "cursor": "p3",
            },
            "p3": {"ok": True, "members": [{"userId": "d@x", "creator": True}]},
        }
        asked: list[str | None] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            fields = _form(request)
            assert fields["chatId"] == "chat@x"
            asked.append(fields.get("cursor"))
            return httpx2.Response(200, json=pages[fields.get("cursor")])

        bot = _bot(handler)
        members = [m async for m in bot.iter_chat_members("chat@x")]
        assert [m["userId"] for m in members] == ["a@x", "b@x", "c@x", "d@x"]
        assert members[2] == {"userId": "c@x", "sn": "c", "nick": "bot_c"}  # nothing is dropped
        assert asked == [None, "p2", "p3"]
        await bot.close()

    async def test_next_page_is_requested_only_when_needed(self):
        asked: list[str | None] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            asked.append(_form(request).get("cursor"))
            return httpx2.Response(
                200, json={"ok": True, "members": [{"userId": "a@x"}], "cursor": "more"}
            )

        bot = _bot(handler)
        async for member in bot.iter_chat_members("chat@x"):
            assert member["userId"] == "a@x"
            break
        assert asked == [None]
        await bot.close()

    async def test_chat_without_members_and_a_repeated_cursor(self, caplog):
        bot = _bot(lambda request: httpx2.Response(200, json={"ok": True}))
        assert [m async for m in bot.iter_chat_members("chat@x")] == []
        await bot.close()

        calls = 0

        def stuck(request: httpx2.Request) -> httpx2.Response:
            nonlocal calls
            calls += 1
            return httpx2.Response(
                200, json={"ok": True, "members": [{"userId": "a@x"}], "cursor": "same"}
            )

        bot = _bot(stuck)
        with caplog.at_level(logging.WARNING, logger="vkworkspace.client.bot"):
            members = [m async for m in bot.iter_chat_members("chat@x")]
        assert len(members) == 2
        assert calls == 2  # the server keeps returning one cursor: the loop ends
        assert "same cursor twice" in caplog.text
        await bot.close()

    async def test_error_of_a_page_is_raised(self):
        bot = _bot(
            lambda request: httpx2.Response(
                200, json={"ok": False, "description": "Permission denied"}
            )
        )
        with pytest.raises(VKTeamsAPIError, match="Permission denied"):
            async for _member in bot.iter_chat_members("chat@x"):
                pass
        await bot.close()
