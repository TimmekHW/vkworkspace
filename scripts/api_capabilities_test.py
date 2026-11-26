"""
VK Teams / VK Workspace — API Capabilities Tester.

Автоматически тестирует ВСЕ доступные методы Bot API и формирует
подробный отчёт: что работает, что запрещено, что требует прав.

Запуск:
    py -3.13 scripts/api_capabilities_test.py

Или с аргументами:
    py -3.13 scripts/api_capabilities_test.py --token "XXX" --url "https://..." --chat-id "user@corp.ru"

Отчёт сохраняется в api_report.txt рядом со скриптом.

(c) vkworkspace framework — автотест для ДИБ / безопасников / аудита.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2 as httpx

# ── Config ────────────────────────────────────────────────────────────

DEFAULT_API_URL = "https://myteam.mail.ru/bot/v1"
TIMEOUT = 15.0


# ── Result model ──────────────────────────────────────────────────────


@dataclass
class MethodResult:
    method: str
    endpoint: str
    status: str = "skip"  # ok, fail, forbidden, timeout, skip, group_only, test_limit
    http_code: int | None = None
    api_ok: bool | None = None
    description: str = ""
    response_keys: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    raw_error: str = ""


# ── Helpers ───────────────────────────────────────────────────────────


async def api_call(
    session: httpx.AsyncClient,
    base_url: str,
    token: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], float]:
    """Make API call, return (http_status, json_body, elapsed_ms)."""
    url = f"{base_url}/{endpoint}"
    p = {"token": token}
    if params:
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                p[k] = "true" if v else "false"
            elif isinstance(v, (list, dict)):
                p[k] = json.dumps(v, ensure_ascii=False)
            else:
                p[k] = v

    t0 = time.monotonic()
    try:
        if files:
            resp = await session.post(url, params=p, files=files)
        else:
            resp = await session.get(url, params=p)
        elapsed = (time.monotonic() - t0) * 1000

        try:
            data = resp.json()
        except Exception:
            data = {"_raw": resp.text[:500]}

        return resp.status_code, data, elapsed

    except httpx.TimeoutException:
        elapsed = (time.monotonic() - t0) * 1000
        return 0, {"_error": "timeout"}, elapsed
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        return 0, {"_error": str(e)}, elapsed


def classify(http_code: int, data: dict) -> tuple[str, str]:
    """Classify result into (status, description)."""
    if http_code == 0:
        err = data.get("_error", "unknown")
        if "timeout" in err:
            return "timeout", f"Таймаут ({TIMEOUT}s)"
        return "fail", f"Ошибка соединения: {err}"

    if http_code == 401:
        return "forbidden", "Неверный токен или нет доступа (401)"
    if http_code == 403:
        return "forbidden", "Запрещено политиками безопасности (403)"
    if http_code == 404:
        return "fail", "Метод не найден (404) — возможно, не поддерживается версией сервера"
    if http_code == 405:
        return "fail", "Method Not Allowed (405)"
    if http_code >= 500:
        return "fail", f"Серверная ошибка ({http_code})"

    # Check API-level response
    if data.get("ok") is True:
        return "ok", "Работает"
    if data.get("ok") is False:
        desc = data.get("description", "")
        if "not" in desc.lower() and "admin" in desc.lower():
            return "forbidden", f"Нет прав администратора: {desc}"
        if "access" in desc.lower() or "permission" in desc.lower():
            return "forbidden", f"Нет доступа: {desc}"
        # "Invalid chatId" = group-only method tested in private chat
        if "invalid chatid" in desc.lower():
            return "group_only", f"Только для групповых чатов (в личке не работает): {desc}"
        # "Invalid file" = test sent fake bytes, not a real format issue
        if "invalid file" in desc.lower():
            return (
                "test_limit",
                f"Эндпоинт доступен (тест не может отправить валидный файл): {desc}",
            )
        # "Unknown method" = not supported by this server version
        if "unknown method" in desc.lower():
            return "fail", f"Не поддерживается этой версией сервера: {desc}"
        return "fail", f"API ошибка: {desc}"

    # Some endpoints return data without "ok" field (e.g. self/get)
    if http_code == 200 and isinstance(data, dict) and not data.get("_error"):
        return "ok", "Работает (ответ без поля 'ok')"

    return "fail", f"Неизвестный ответ (HTTP {http_code})"


# ── Test groups ───────────────────────────────────────────────────────


async def test_self(
    session: httpx.AsyncClient, base: str, token: str, **_: Any
) -> list[MethodResult]:
    """Тест: информация о боте."""
    results = []

    code, data, ms = await api_call(session, base, token, "self/get")
    status, desc = classify(code, data)
    r = MethodResult(
        method="Получить информацию о боте",
        endpoint="self/get",
        status=status,
        http_code=code,
        api_ok=data.get("ok"),
        description=desc,
        elapsed_ms=ms,
        response_keys=list(data.keys()) if isinstance(data, dict) else [],
    )
    if status == "ok" and "userId" in data:
        r.description = f"Работает — бот: {data.get('firstName', '?')} ({data.get('userId', '?')})"
    results.append(r)

    return results


async def test_messages(
    session: httpx.AsyncClient, base: str, token: str, chat_id: str, **_: Any
) -> list[MethodResult]:
    """Тест: отправка, редактирование, удаление сообщений."""
    results = []
    sent_msg_id: str | None = None

    # 1. Send text
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/sendText",
        {
            "chatId": chat_id,
            "text": "🔬 API Capabilities Test — отправка текста",
        },
    )
    status, desc = classify(code, data)
    r = MethodResult(
        "Отправить текст",
        "messages/sendText",
        status=status,
        http_code=code,
        api_ok=data.get("ok"),
        description=desc,
        elapsed_ms=ms,
        response_keys=list(data.keys()) if isinstance(data, dict) else [],
    )
    if status == "ok":
        sent_msg_id = data.get("msgId")
        r.description = f"Работает — msgId: {sent_msg_id}"
    results.append(r)

    # 2. Send with inline keyboard
    keyboard = json.dumps(
        [
            [
                {"text": "✅ Тест кнопки", "callbackData": "cap_test_btn", "style": "primary"},
                {"text": "🔗 URL", "url": "https://example.com", "style": "attention"},
            ]
        ]
    )
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/sendText",
        {
            "chatId": chat_id,
            "text": "🔬 Тест inline-кнопок",
            "inlineKeyboardMarkup": keyboard,
        },
    )
    status, desc = classify(code, data)
    btn_msg_id = data.get("msgId") if data.get("ok") else None
    results.append(
        MethodResult(
            "Отправить текст с кнопками",
            "messages/sendText + inlineKeyboardMarkup",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 3. Send with format (bold, italic)
    fmt = json.dumps({"bold": [{"offset": 0, "length": 4}], "italic": [{"offset": 5, "length": 4}]})
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/sendText",
        {
            "chatId": chat_id,
            "text": "Bold Italic test",
            "format": fmt,
        },
    )
    status, desc = classify(code, data)
    fmt_msg_id = data.get("msgId") if data.get("ok") else None
    results.append(
        MethodResult(
            "Отправить форматированный текст",
            "messages/sendText + format",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 4. Edit text
    target = sent_msg_id or "0"
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/editText",
        {
            "chatId": chat_id,
            "msgId": target,
            "text": "🔬 API Test — текст отредактирован",
        },
    )
    status, desc = classify(code, data)
    if not sent_msg_id:
        status, desc = "skip", "Пропущено — нет msgId от sendText"
    results.append(
        MethodResult(
            "Редактировать текст",
            "messages/editText",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 5. Send file (upload small text file)
    test_content = b"vkworkspace API capabilities test file"
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/sendFile",
        {"chatId": chat_id, "caption": "Тестовый файл"},
        files={"file": ("test_capabilities.txt", io.BytesIO(test_content))},
    )
    status, desc = classify(code, data)
    file_id = data.get("fileId")
    if status == "ok" and file_id:
        desc = f"Работает — fileId: {file_id}"
    results.append(
        MethodResult(
            "Отправить файл (upload)",
            "messages/sendFile",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 6. Send voice (upload small audio)
    # Voice requires AAC/OGG, but we test if the endpoint accepts requests at all
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/sendVoice",
        {"chatId": chat_id},
        files={"file": ("test.aac", io.BytesIO(b"\x00" * 100))},
    )
    status, desc = classify(code, data)
    results.append(
        MethodResult(
            "Отправить голосовое (upload)",
            "messages/sendVoice",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 7. Delete message
    targets_to_delete = [m for m in [btn_msg_id, fmt_msg_id] if m]
    if targets_to_delete:
        code, data, ms = await api_call(
            session,
            base,
            token,
            "messages/deleteMessages",
            {
                "chatId": chat_id,
                "msgId": targets_to_delete[0],
            },
        )
        status, desc = classify(code, data)
    else:
        code, data, ms, status, desc = 0, {}, 0, "skip", "Пропущено — нет сообщений для удаления"
    results.append(
        MethodResult(
            "Удалить сообщение",
            "messages/deleteMessages",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 8. Answer callback query (fake — no real queryId, but test if endpoint responds)
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/answerCallbackQuery",
        {
            "queryId": "TEST:fake:query:id",
            "text": "test",
        },
    )
    status, desc = classify(code, data)
    # This will likely fail with "query not found" which is still informative
    if status == "fail" and "query" in data.get("description", "").lower():
        status = "ok"
        desc = "Эндпоинт доступен (ожидаемая ошибка: queryId невалидный)"
    results.append(
        MethodResult(
            "Ответ на callback query",
            "messages/answerCallbackQuery",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    return results


async def test_chats(
    session: httpx.AsyncClient, base: str, token: str, chat_id: str, **_: Any
) -> list[MethodResult]:
    """Тест: управление чатами."""
    results = []

    # 1. Get chat info
    code, data, ms = await api_call(session, base, token, "chats/getInfo", {"chatId": chat_id})
    status, desc = classify(code, data)
    if status == "ok":
        chat_type = data.get("type", "?")
        title = data.get("title") or data.get("firstName") or chat_id
        desc = f"Работает — тип: {chat_type}, название: {title}"
    results.append(
        MethodResult(
            "Получить информацию о чате",
            "chats/getInfo",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
            response_keys=list(data.keys()) if isinstance(data, dict) else [],
        )
    )

    # 2. Get admins
    code, data, ms = await api_call(session, base, token, "chats/getAdmins", {"chatId": chat_id})
    status, desc = classify(code, data)
    if status == "ok":
        admins = data.get("admins", [])
        desc = f"Работает — {len(admins)} админ(ов)"
    results.append(
        MethodResult(
            "Получить админов чата",
            "chats/getAdmins",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 3. Get members
    code, data, ms = await api_call(session, base, token, "chats/getMembers", {"chatId": chat_id})
    status, desc = classify(code, data)
    if status == "ok":
        members = data.get("members", [])
        desc = f"Работает — {len(members)} участник(ов) на странице"
    results.append(
        MethodResult(
            "Получить участников чата",
            "chats/getMembers",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 4. Get blocked users
    code, data, ms = await api_call(
        session, base, token, "chats/getBlockedUsers", {"chatId": chat_id}
    )
    status, desc = classify(code, data)
    results.append(
        MethodResult(
            "Получить заблокированных",
            "chats/getBlockedUsers",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 5. Get pending users
    code, data, ms = await api_call(
        session, base, token, "chats/getPendingUsers", {"chatId": chat_id}
    )
    status, desc = classify(code, data)
    results.append(
        MethodResult(
            "Ожидающие вступления",
            "chats/getPendingUsers",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 6. Send actions (typing)
    code, data, ms = await api_call(
        session,
        base,
        token,
        "chats/sendActions",
        {
            "chatId": chat_id,
            "actions": "typing",
        },
    )
    status, desc = classify(code, data)
    results.append(
        MethodResult(
            "Отправить 'печатает...'",
            "chats/sendActions",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    # 7-8. Pin / Unpin (need a message) — send a temp message to pin
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/sendText",
        {
            "chatId": chat_id,
            "text": "📌 Тест закрепления",
        },
    )
    pin_msg_id = data.get("msgId") if data.get("ok") else None

    if pin_msg_id:
        code, data, ms = await api_call(
            session,
            base,
            token,
            "chats/pinMessage",
            {
                "chatId": chat_id,
                "msgId": pin_msg_id,
            },
        )
        status, desc = classify(code, data)
    else:
        code, ms, status, desc = 0, 0, "skip", "Пропущено — не удалось отправить сообщение"
    results.append(
        MethodResult(
            "Закрепить сообщение",
            "chats/pinMessage",
            status=status,
            http_code=code,
            description=desc,
            elapsed_ms=ms,
        )
    )

    if pin_msg_id:
        code, data, ms = await api_call(
            session,
            base,
            token,
            "chats/unpinMessage",
            {
                "chatId": chat_id,
                "msgId": pin_msg_id,
            },
        )
        status, desc = classify(code, data)
    else:
        code, ms, status, desc = 0, 0, "skip", "Пропущено"
    results.append(
        MethodResult(
            "Открепить сообщение",
            "chats/unpinMessage",
            status=status,
            http_code=code,
            description=desc,
            elapsed_ms=ms,
        )
    )

    # Cleanup pin message
    if pin_msg_id:
        await api_call(
            session,
            base,
            token,
            "messages/deleteMessages",
            {
                "chatId": chat_id,
                "msgId": pin_msg_id,
            },
        )

    # 9-11. Title/About/Rules — only safe to test on group chats
    # We try but expect failures on private chats
    for name, endpoint, key, value in [
        ("Установить название чата", "chats/setTitle", "title", None),
        ("Установить описание чата", "chats/setAbout", "about", None),
        ("Установить правила чата", "chats/setRules", "rules", None),
    ]:
        code, data, ms = await api_call(
            session,
            base,
            token,
            endpoint,
            {
                "chatId": chat_id,
                key: value or "test",
            },
        )
        status, desc = classify(code, data)
        if status == "ok":
            desc = "Доступен (тест с фиктивным значением)"
        results.append(
            MethodResult(
                name,
                endpoint,
                status=status,
                http_code=code,
                api_ok=data.get("ok"),
                description=desc,
                elapsed_ms=ms,
            )
        )

    return results


async def test_files(
    session: httpx.AsyncClient, base: str, token: str, chat_id: str, **_: Any
) -> list[MethodResult]:
    """Тест: файловые операции."""
    results = []

    # Upload a file first to get fileId
    content = b"capabilities test file content"
    code, data, ms = await api_call(
        session,
        base,
        token,
        "messages/sendFile",
        {"chatId": chat_id, "caption": "файл для getInfo теста"},
        files={"file": ("cap_test.txt", io.BytesIO(content))},
    )
    file_id = data.get("fileId") if data.get("ok") else None
    cleanup_msg = data.get("msgId")

    if file_id:
        code2, data2, ms2 = await api_call(
            session, base, token, "files/getInfo", {"fileId": file_id}
        )
        status, desc = classify(code2, data2)
        if status == "ok":
            desc = f"Работает — {data2.get('filename', '?')}, {data2.get('size', '?')} байт, тип: {data2.get('type', '?')}"
        results.append(
            MethodResult(
                "Получить информацию о файле",
                "files/getInfo",
                status=status,
                http_code=code2,
                api_ok=data2.get("ok"),
                description=desc,
                elapsed_ms=ms2,
                response_keys=list(data2.keys()) if isinstance(data2, dict) else [],
            )
        )
    else:
        results.append(
            MethodResult(
                "Получить информацию о файле",
                "files/getInfo",
                status="skip",
                description="Пропущено — не удалось загрузить файл",
            )
        )

    # Send file by fileId (re-send)
    if file_id:
        code, data, ms = await api_call(
            session,
            base,
            token,
            "messages/sendFile",
            {
                "chatId": chat_id,
                "fileId": file_id,
                "caption": "отправка по fileId",
            },
        )
        status, desc = classify(code, data)
        resend_msg = data.get("msgId")
        results.append(
            MethodResult(
                "Отправить файл по fileId",
                "messages/sendFile (fileId)",
                status=status,
                http_code=code,
                api_ok=data.get("ok"),
                description=desc,
                elapsed_ms=ms,
            )
        )
        # Cleanup
        if resend_msg:
            await api_call(
                session,
                base,
                token,
                "messages/deleteMessages",
                {
                    "chatId": chat_id,
                    "msgId": resend_msg,
                },
            )
    else:
        results.append(
            MethodResult(
                "Отправить файл по fileId",
                "messages/sendFile (fileId)",
                status="skip",
                description="Пропущено",
            )
        )

    # Cleanup
    if cleanup_msg:
        await api_call(
            session,
            base,
            token,
            "messages/deleteMessages",
            {
                "chatId": chat_id,
                "msgId": cleanup_msg,
            },
        )

    return results


async def test_threads(
    session: httpx.AsyncClient, base: str, token: str, chat_id: str, **_: Any
) -> list[MethodResult]:
    """Тест: треды (threads)."""
    results = []

    # Try to get thread subscribers (will fail without real threadId, but tests endpoint availability)
    code, data, ms = await api_call(
        session,
        base,
        token,
        "threads/subscribers/get",
        {
            "threadId": "fake_thread_id",
        },
    )
    status, desc = classify(code, data)
    if status == "fail" and code == 200:
        status = "ok"
        desc = "Эндпоинт доступен (ожидаемая ошибка: threadId невалидный)"
    elif code == 404:
        status = "fail"
        desc = "Треды не поддерживаются этой версией сервера (404)"
    results.append(
        MethodResult(
            "Подписчики треда",
            "threads/subscribers/get",
            status=status,
            http_code=code,
            description=desc,
            elapsed_ms=ms,
        )
    )

    # threads/autosubscribe
    code, data, ms = await api_call(
        session,
        base,
        token,
        "threads/autosubscribe",
        {
            "chatId": chat_id,
            "enable": True,
        },
    )
    status, desc = classify(code, data)
    if code == 404:
        desc = "Треды не поддерживаются этой версией сервера (404)"
    results.append(
        MethodResult(
            "Автоподписка на треды",
            "threads/autosubscribe",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
        )
    )

    return results


async def test_events(
    session: httpx.AsyncClient, base: str, token: str, **_: Any
) -> list[MethodResult]:
    """Тест: получение событий (long poll)."""
    results = []

    code, data, ms = await api_call(
        session,
        base,
        token,
        "events/get",
        {
            "lastEventId": 0,
            "pollTime": 1,  # 1 second poll — quick check
        },
    )
    status, desc = classify(code, data)
    if status == "ok":
        events = data.get("events", [])
        desc = f"Работает — получено {len(events)} событий за 1с"
    results.append(
        MethodResult(
            "Long polling (events/get)",
            "events/get",
            status=status,
            http_code=code,
            api_ok=data.get("ok"),
            description=desc,
            elapsed_ms=ms,
            response_keys=list(data.keys()) if isinstance(data, dict) else [],
        )
    )

    return results


# ── Report ────────────────────────────────────────────────────────────

STATUS_ICON = {
    "ok": "✅",
    "fail": "❌",
    "forbidden": "🔒",
    "timeout": "⏱️",
    "skip": "⏭️",
    "group_only": "👥",
    "test_limit": "⚠️",
}

STATUS_LABEL = {
    "ok": "Доступен",
    "fail": "Ошибка",
    "forbidden": "Запрещён",
    "timeout": "Таймаут",
    "skip": "Пропущен",
    "group_only": "Только для групп",
    "test_limit": "Доступен (ограничение теста)",
}


def build_report(
    all_results: list[MethodResult],
    bot_info: dict[str, Any],
    api_url: str,
    chat_id: str,
) -> str:
    lines: list[str] = []

    lines.append("=" * 72)
    lines.append("  VK TEAMS / VK WORKSPACE — ОТЧЁТ О ВОЗМОЖНОСТЯХ BOT API")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"  Дата:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  API URL:    {api_url}")
    lines.append(f"  Chat ID:    {chat_id}")
    if bot_info:
        lines.append(
            f"  Бот:        {bot_info.get('firstName', '?')} (@{bot_info.get('nick', '?')})"
        )
        lines.append(f"  Bot ID:     {bot_info.get('userId', '?')}")
    lines.append("")

    # Summary counts
    counts: dict[str, int] = {}
    for r in all_results:
        counts[r.status] = counts.get(r.status, 0) + 1
    total = len(all_results)
    tested = total - counts.get("skip", 0)

    # "effectively available" = ok + group_only + test_limit
    available = counts.get("ok", 0) + counts.get("group_only", 0) + counts.get("test_limit", 0)

    lines.append("─" * 72)
    lines.append("  СВОДКА")
    lines.append("─" * 72)
    lines.append(f"  Всего методов проверено:  {tested} / {total}")
    lines.append(f"  {STATUS_ICON['ok']} Доступно:                {counts.get('ok', 0)}")
    lines.append(
        f"  {STATUS_ICON['group_only']} Только для групп:        {counts.get('group_only', 0)}  (работает, но тест был в личке)"
    )
    lines.append(
        f"  {STATUS_ICON['test_limit']} Ограничение теста:       {counts.get('test_limit', 0)}  (эндпоинт доступен, тест ограничен)"
    )
    lines.append(
        f"  {STATUS_ICON['forbidden']} Запрещено (политики):    {counts.get('forbidden', 0)}"
    )
    lines.append(f"  {STATUS_ICON['fail']} Ошибки / не поддерж.:    {counts.get('fail', 0)}")
    lines.append(f"  {STATUS_ICON['timeout']} Таймауты:                {counts.get('timeout', 0)}")
    lines.append(f"  {STATUS_ICON['skip']} Пропущено:               {counts.get('skip', 0)}")
    lines.append("")

    if tested > 0:
        pct = available / tested * 100
        bar_len = 30
        filled = int(bar_len * available // tested)
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"  Реальная доступность: [{bar}] {pct:.0f}% ({available}/{tested})")
        lines.append("")

    # Group results by category
    groups = [
        ("ИНФОРМАЦИЯ О БОТЕ", [r for r in all_results if r.endpoint == "self/get"]),
        ("СОБЫТИЯ (POLLING)", [r for r in all_results if "events/" in r.endpoint]),
        (
            "СООБЩЕНИЯ",
            [r for r in all_results if "messages/" in r.endpoint or "sendText" in r.endpoint],
        ),
        ("ЧАТЫ", [r for r in all_results if "chats/" in r.endpoint]),
        ("ФАЙЛЫ", [r for r in all_results if "files/" in r.endpoint or "fileId" in r.endpoint]),
        ("ТРЕДЫ", [r for r in all_results if "threads/" in r.endpoint]),
    ]

    for group_name, group_results in groups:
        if not group_results:
            continue

        lines.append("─" * 72)
        lines.append(f"  {group_name}")
        lines.append("─" * 72)

        for r in group_results:
            icon = STATUS_ICON.get(r.status, "?")
            label = STATUS_LABEL.get(r.status, r.status)
            lines.append(f"  {icon} {r.method}")
            lines.append(f"     Эндпоинт: {r.endpoint}")
            lines.append(
                f"     Статус:   {label} | HTTP {r.http_code or '-'} | {r.elapsed_ms:.0f}ms"
            )
            lines.append(f"     Детали:   {r.description}")
            if r.response_keys:
                lines.append(f"     Поля:     {', '.join(r.response_keys)}")
            lines.append("")

    # Recommendations
    lines.append("═" * 72)
    lines.append("  РЕКОМЕНДАЦИИ")
    lines.append("═" * 72)

    group_only = [r for r in all_results if r.status == "group_only"]
    test_limit = [r for r in all_results if r.status == "test_limit"]
    forbidden = [r for r in all_results if r.status == "forbidden"]
    failed = [r for r in all_results if r.status == "fail"]

    has_issues = forbidden or failed

    if group_only:
        lines.append("")
        lines.append(f"  👥 Методы, требующие группового чата ({len(group_only)} шт.):")
        lines.append("     Тест запускался в личке — эти методы работают только в группах/каналах.")
        lines.append("     Для полной проверки добавьте бота в групповой чат и укажите его chatId.")
        for r in group_only:
            lines.append(f"       • {r.method} ({r.endpoint})")

    if test_limit:
        lines.append("")
        lines.append(f"  ⚠️ Ограничения теста ({len(test_limit)} шт.):")
        lines.append("     Эндпоинты доступны, но тест не может сгенерировать валидные данные.")
        for r in test_limit:
            lines.append(f"       • {r.method} ({r.endpoint})")

    if forbidden:
        lines.append("")
        lines.append(
            f"  🔒 Запрещённые методы ({len(forbidden)} шт.) — требуют согласования с ДИБ:"
        )
        for r in forbidden:
            lines.append(f"       • {r.method} ({r.endpoint})")
            lines.append(f"         → {r.description}")

    if failed:
        lines.append("")
        lines.append(f"  ❌ Не поддерживается сервером ({len(failed)} шт.):")
        for r in failed:
            lines.append(f"       • {r.method} ({r.endpoint})")
            lines.append(f"         → {r.description}")

    if not has_issues and not group_only and not test_limit:
        lines.append("  🎉 Все проверенные методы доступны! Ограничений не обнаружено.")
    elif not has_issues:
        lines.append("")
        lines.append("  ✅ Реальных ограничений не обнаружено! Все методы доступны.")

    lines.append("")
    lines.append("═" * 72)
    lines.append("  Отчёт сгенерирован vkworkspace API Capabilities Tester")
    lines.append("═" * 72)

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────


async def main(token: str, api_url: str, chat_id: str) -> None:
    print("=" * 50)
    print("  VK Teams API Capabilities Tester")
    print("=" * 50)
    print()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT + 5, connect=10.0),
        follow_redirects=True,
    ) as session:
        # 0. Pre-flight: check bot identity
        print("[1/6] Проверка бота (self/get)...")
        bot_info: dict[str, Any] = {}
        code, data, _ = await api_call(session, api_url, token, "self/get")
        if code == 200 and isinstance(data, dict) and data.get("userId"):
            bot_info = data
            print(f"       Бот: {data.get('firstName', '?')} (@{data.get('nick', '?')})")
        else:
            print(f"       ⚠️  Не удалось получить info о боте (HTTP {code})")
            print("       Проверьте TOKEN и API_URL!")
            if code == 0:
                print(f"       Ошибка: {data.get('_error', '?')}")
                return

        all_results: list[MethodResult] = []

        # 1. Self
        print("[2/6] Тестирование: информация о боте...")
        all_results.extend(await test_self(session, api_url, token))

        # 2. Events
        print("[3/6] Тестирование: events/get (polling)...")
        all_results.extend(await test_events(session, api_url, token))

        # 3. Messages
        print("[4/6] Тестирование: сообщения...")
        all_results.extend(await test_messages(session, api_url, token, chat_id))

        # 4. Chats
        print("[5/6] Тестирование: чаты...")
        all_results.extend(await test_chats(session, api_url, token, chat_id))

        # 5. Files
        print("[6/6] Тестирование: файлы и треды...")
        all_results.extend(await test_files(session, api_url, token, chat_id))
        all_results.extend(await test_threads(session, api_url, token, chat_id))

    # Build report
    report = build_report(all_results, bot_info, api_url, chat_id)

    # Save
    report_path = Path(__file__).parent / "api_report.txt"
    report_path.write_text(report, encoding="utf-8")

    # Also save JSON for programmatic use
    json_path = Path(__file__).parent / "api_report.json"
    json_data = {
        "timestamp": datetime.now().isoformat(),
        "api_url": api_url,
        "chat_id": chat_id,
        "bot": bot_info,
        "results": [
            {
                "method": r.method,
                "endpoint": r.endpoint,
                "status": r.status,
                "http_code": r.http_code,
                "description": r.description,
                "elapsed_ms": round(r.elapsed_ms, 1),
                "response_keys": r.response_keys,
            }
            for r in all_results
        ],
    }
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print report
    print()
    print(report)
    print()
    print(f"📄 Отчёт сохранён: {report_path}")
    print(f"📊 JSON отчёт:     {json_path}")

    # Send report summary to chat
    ok_count = sum(1 for r in all_results if r.status == "ok")
    group_only_count = sum(1 for r in all_results if r.status == "group_only")
    test_limit_count = sum(1 for r in all_results if r.status == "test_limit")
    total = len(all_results)
    skip = sum(1 for r in all_results if r.status == "skip")
    tested = total - skip
    available = ok_count + group_only_count + test_limit_count
    forbidden_count = sum(1 for r in all_results if r.status == "forbidden")
    fail_count = sum(1 for r in all_results if r.status == "fail")

    summary = (
        f"📋 API Capabilities Report\n\nПроверено методов: {tested}\n✅ Доступно: {ok_count}\n"
    )
    if group_only_count:
        summary += f"👥 Только для групп: {group_only_count} (тест в личке)\n"
    if test_limit_count:
        summary += f"⚠️ Ограничение теста: {test_limit_count}\n"
    if forbidden_count:
        summary += f"🔒 Запрещено: {forbidden_count}\n"
    if fail_count:
        summary += f"❌ Не поддерживается: {fail_count}\n"
    summary += f"\nРеальная доступность: {available}/{tested} ({available * 100 // tested}%)\n\n"

    forbidden_list = [r for r in all_results if r.status == "forbidden"]
    if forbidden_list:
        summary += "Запрещённые:\n"
        for r in forbidden_list:
            summary += f"  🔒 {r.endpoint}\n"
        summary += "\n"

    fail_list = [r for r in all_results if r.status == "fail"]
    if fail_list:
        summary += "Не поддерживается сервером:\n"
        for r in fail_list:
            summary += f"  ❌ {r.endpoint}\n"

    if not forbidden_list and not fail_list:
        summary += "🎉 Реальных ограничений нет! Все методы доступны."

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=True) as s:
        await api_call(
            s,
            api_url,
            token,
            "messages/sendText",
            {
                "chatId": chat_id,
                "text": summary,
            },
        )
    print("\n✉️  Краткий отчёт отправлен в чат")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VK Teams API Capabilities Tester")
    parser.add_argument("--token", "-t", help="Bot token")
    parser.add_argument("--url", "-u", help="API base URL", default=DEFAULT_API_URL)
    parser.add_argument("--chat-id", "-c", help="Chat ID for testing (your email)")
    args = parser.parse_args()

    token = args.token
    url = args.url
    chat_id = args.chat_id

    if not token:
        token = input("🔑 Bot Token: ").strip()
    if not url or url == DEFAULT_API_URL:
        custom_url = input(f"🌐 API URL [{DEFAULT_API_URL}]: ").strip()
        if custom_url:
            url = custom_url
    if not chat_id:
        chat_id = input("💬 Chat ID (ваш email): ").strip()

    if not token or not chat_id:
        print("❌ Token и Chat ID обязательны!")
        sys.exit(1)

    url = url.rstrip("/")

    asyncio.run(main(token, url, chat_id))
