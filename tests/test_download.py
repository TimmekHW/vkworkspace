"""Tests for file download — especially the token ``:`` / ``%3A`` bug.

The VK Teams file host rejects a download whose ``token`` query param has its
``:`` percent‑encoded to ``%3A`` (answering HTTP 500). These tests pin the
correct behaviour: the token is appended to the URL string and sent verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from vkworkspace.client.bot import Bot
from vkworkspace.exceptions import FileDownloadError

pytestmark = pytest.mark.asyncio

# On‑prem bot token — note the ``:`` that must survive to the wire.
TOKEN = "001.3033835949.2221539346:1000001942"
API_URL = "https://api.teams.sovcombank.test/bot/v1"
FILE_URL = (
    "https://ub.teams.sovcombank.test/files/get/fvbxHASH_-x/api-ms-win-core-handle-l1-1-0.dll"
)
PAYLOAD = b"MZ\x90\x00\x03binary-dll-bytes"


def _bot(handler: Any, **kwargs: Any) -> Bot:
    bot = Bot(token=TOKEN, api_url=API_URL, retry_on_5xx=kwargs.pop("retry_on_5xx", 0), **kwargs)
    bot._session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return bot


async def test_token_colon_not_percent_encoded():
    """The whole point: ``:`` in the token must reach the wire, not ``%3A``."""
    captured: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["query"] = req.url.query.decode()
        return httpx.Response(200, content=PAYLOAD)

    bot = _bot(handler)
    data = await bot.download_file_by_url(FILE_URL)
    await bot.close()

    assert data == PAYLOAD
    assert captured["query"] == f"token={TOKEN}"
    assert ":1000001942" in captured["query"]
    assert "%3A" not in captured["query"]


async def test_download_by_file_id_resolves_info():
    """``download_file`` calls files/getInfo then GETs the returned URL."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/files/getInfo"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "type": "file",
                    "size": len(PAYLOAD),
                    "filename": "report.pdf",
                    "url": FILE_URL,
                },
            )
        assert "%3A" not in req.url.query.decode()
        return httpx.Response(200, content=PAYLOAD)

    bot = _bot(handler)
    data = await bot.download_file("some-file-id")
    await bot.close()
    assert data == PAYLOAD


async def test_save_to_directory_uses_server_filename(tmp_path: Path):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PAYLOAD)

    bot = _bot(handler)
    path = await bot.download_file_by_url(FILE_URL, tmp_path)
    await bot.close()

    assert isinstance(path, Path)
    assert path.name == "api-ms-win-core-handle-l1-1-0.dll"
    assert path.read_bytes() == PAYLOAD


async def test_save_to_exact_path(tmp_path: Path):
    dest = tmp_path / "sub" / "out.bin"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PAYLOAD)

    bot = _bot(handler)
    path = await bot.download_file_by_url(FILE_URL, dest)
    await bot.close()
    assert path == dest
    assert dest.read_bytes() == PAYLOAD


async def test_no_double_token_if_url_already_signed():
    captured: dict[str, str] = {}
    signed = f"{FILE_URL}?token=already-here"

    def handler(req: httpx.Request) -> httpx.Response:
        captured["query"] = req.url.query.decode()
        return httpx.Response(200, content=PAYLOAD)

    bot = _bot(handler)
    await bot.download_file_by_url(signed)
    await bot.close()
    assert captured["query"] == "token=already-here"
    assert TOKEN not in captured["query"]


async def test_append_token_false():
    captured: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["query"] = req.url.query.decode()
        return httpx.Response(200, content=PAYLOAD)

    bot = _bot(handler)
    await bot.download_file_by_url(FILE_URL, append_token=False)
    await bot.close()
    assert captured["query"] == ""


async def test_500_raises_file_download_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    bot = _bot(handler, retry_on_5xx=0)
    with pytest.raises(FileDownloadError):
        await bot.download_file_by_url(FILE_URL)
    await bot.close()


async def test_500_then_retry_succeeds():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, content=b"transient")
        return httpx.Response(200, content=PAYLOAD)

    bot = _bot(handler, retry_on_5xx=2)
    data = await bot.download_file_by_url(FILE_URL)
    await bot.close()
    assert data == PAYLOAD
    assert calls["n"] == 2


async def test_missing_url_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "filename": "x", "url": None})

    bot = _bot(handler)
    with pytest.raises(FileDownloadError):
        await bot.download_file("fid")
    await bot.close()


# ── aiogram-style: download straight off the Message ────────────────────


def _getinfo_then_file(handler_body: bytes = PAYLOAD) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/files/getInfo"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "type": "image",
                    "size": len(handler_body),
                    "filename": "photo.jpg",
                    "url": FILE_URL,
                },
            )
        assert "%3A" not in req.url.query.decode()
        return httpx.Response(200, content=handler_body)

    return handler


def _message_with_file(bot: Bot) -> Any:
    from vkworkspace.types.message import Message

    msg = Message.model_validate(
        {
            "msgId": "1",
            "chat": {"chatId": "c@chat", "type": "private"},
            "parts": [
                {"type": "file", "payload": {"fileId": "F1", "type": "image", "caption": "hi"}}
            ],
        }
    )
    msg.set_bot(bot)
    return msg


async def test_message_download_to_memory():
    bot = _bot(_getinfo_then_file())
    msg = _message_with_file(bot)
    data = await msg.download()
    await bot.close()
    assert data == PAYLOAD


async def test_message_download_to_dir(tmp_path: Path):
    bot = _bot(_getinfo_then_file())
    msg = _message_with_file(bot)
    path = await msg.download(tmp_path)
    await bot.close()
    assert isinstance(path, Path)
    assert path.name == "photo.jpg"
    assert path.read_bytes() == PAYLOAD


async def test_filepayload_download_directly():
    bot = _bot(_getinfo_then_file())
    msg = _message_with_file(bot)
    data = await msg.files[0].download()
    await bot.close()
    assert data == PAYLOAD


async def test_message_download_no_attachments_raises():
    from vkworkspace.types.message import Message

    bot = _bot(_getinfo_then_file())
    msg = Message.model_validate(
        {"msgId": "1", "chat": {"chatId": "c@chat", "type": "private"}, "text": "hi"}
    )
    msg.set_bot(bot)
    with pytest.raises(ValueError, match="no downloadable"):
        await msg.download()
    await bot.close()


async def test_bot_download_accepts_payload():
    bot = _bot(_getinfo_then_file())
    msg = _message_with_file(bot)
    data = await bot.download(msg.files[0])
    await bot.close()
    assert data == PAYLOAD
