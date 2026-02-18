"""
Diagnostic bot — captures ALL raw data from VK Teams API to a JSONL log file.

Purpose: reverse-engineer undocumented features, discover new event types,
find changed payload structures, and document every field the API sends.

Usage:
    python scripts/diagnostic_bot.py

    Then send the bot: text, images, stickers, voice, files, forwards, replies,
    reactions, polls, callback buttons, inline queries, add/remove users,
    pin/unpin, change chat info — EVERYTHING.

    All raw data is saved to `diagnostic_log.jsonl`.
    Give this file to the developer for analysis.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# ── Path setup ─────────────────────────────────────────────────────────────
# Allow running from examples/ without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vkworkspace.utils.keyboard import InlineKeyboardBuilder

# ── Config ─────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("VK_BOT_TOKEN", "YOUR_BOT_TOKEN")
API_URL = os.environ.get("VK_API_URL", "https://myteam.mail.ru/bot/v1")
LOG_FILE = Path(__file__).parent / "diagnostic_log.jsonl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("diagnostic")


# ── JSONL logger ───────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now(UTC).isoformat()


def write_log(entry: dict[str, Any]) -> None:
    """Append one JSON line to the log file."""
    entry.setdefault("_ts", ts())
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def safe_dump(obj: Any) -> Any:
    """Make anything JSON-serializable."""
    if isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"
    if isinstance(obj, (dict, list, str, int, float, bool, type(None))):
        return obj
    return str(obj)


# ── Raw HTTP client (no Pydantic, pure JSON logging) ──────────────────────

class DiagnosticClient:
    """
    Minimal VK Teams API client that logs EVERYTHING.
    Does NOT parse into Pydantic models — saves raw JSON as-is.
    """

    def __init__(self, token: str, api_url: str) -> None:
        self.token = token
        self.api_url = api_url.rstrip("/")
        self._session: httpx.AsyncClient | None = None
        self._last_event_id: int = 0

    async def session(self) -> httpx.AsyncClient:
        if self._session is None or self._session.is_closed:
            self._session = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=10.0),
                follow_redirects=True,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.is_closed:
            await self._session.aclose()

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        log_response: bool = True,
    ) -> dict[str, Any]:
        s = await self.session()
        url = f"{self.api_url}/{method}"
        p = {"token": self.token, **(params or {})}

        # Log outgoing request
        safe_params = {k: v for k, v in p.items() if k != "token"}
        write_log({
            "_type": "API_REQUEST",
            "method": method,
            "params": safe_params,
        })

        resp = await s.get(url, params=p)
        raw_text = resp.text

        try:
            data = resp.json()
        except Exception:
            data = {"_raw_text": raw_text, "_status": resp.status_code}

        if log_response:
            write_log({
                "_type": "API_RESPONSE",
                "method": method,
                "status_code": resp.status_code,
                "data": data,
            })

        return data

    async def get_events(self, poll_time: int = 60) -> list[dict[str, Any]]:
        data = await self.request(
            "events/get",
            {"pollTime": poll_time, "lastEventId": self._last_event_id},
            log_response=False,  # we log events individually below
        )
        events = data.get("events", [])

        if events:
            write_log({
                "_type": "POLL_BATCH",
                "count": len(events),
                "event_ids": [e.get("eventId") for e in events],
            })

        for ev in events:
            eid = ev.get("eventId", 0)
            if eid > self._last_event_id:
                self._last_event_id = eid

            # === THE MAIN LOG: every raw event, untouched ===
            write_log({
                "_type": "RAW_EVENT",
                "eventId": eid,
                "type": ev.get("type", "UNKNOWN"),
                "payload": ev.get("payload", {}),
                "_full_event": ev,  # keep the entire object in case there are extra keys
            })

        return events

    async def send_text(
        self,
        chat_id: str,
        text: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"chatId": chat_id, "text": text}
        for k, v in kwargs.items():
            if v is not None:
                params[k] = v
        return await self.request("messages/sendText", params)

    async def answer_callback(
        self,
        query_id: str,
        text: str = "",
        show_alert: bool = False,
    ) -> dict[str, Any]:
        params = {"queryId": query_id, "text": text}
        if show_alert:
            params["showAlert"] = "true"
        return await self.request("messages/answerCallbackQuery", params)

    async def get_me(self) -> dict[str, Any]:
        return await self.request("self/get")

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        return await self.request("chats/getInfo", {"chatId": chat_id})

    async def get_chat_admins(self, chat_id: str) -> dict[str, Any]:
        return await self.request("chats/getAdmins", {"chatId": chat_id})

    async def get_chat_members(self, chat_id: str) -> dict[str, Any]:
        return await self.request("chats/getMembers", {"chatId": chat_id})

    async def get_file_info(self, file_id: str) -> dict[str, Any]:
        return await self.request("files/getInfo", {"fileId": file_id})


# ── Event analysis helpers ─────────────────────────────────────────────────

KNOWN_EVENT_TYPES = {
    "newMessage", "editedMessage", "deletedMessage",
    "pinnedMessage", "unpinnedMessage",
    "newChatMembers", "leftChatMembers", "changedChatInfo",
    "callbackQuery",
}

KNOWN_MESSAGE_FIELDS = {
    "msgId", "chat", "from", "text", "timestamp", "format", "parts",
    "editedTimestamp",
}

KNOWN_PART_TYPES = {
    "sticker", "mention", "voice", "file", "forward", "reply", "inline_keyboard",
}

KNOWN_CALLBACK_FIELDS = {
    "queryId", "from", "message", "callbackData", "chat",
}


def analyze_event(event: dict[str, Any]) -> dict[str, Any]:
    """Detect anything unusual or undocumented in the event."""
    findings: list[str] = []
    event_type = event.get("type", "")
    payload = event.get("payload", {})

    # 1. Unknown event type?
    if event_type not in KNOWN_EVENT_TYPES:
        findings.append(f"UNKNOWN EVENT TYPE: '{event_type}'")

    # 2. Extra top-level keys in the event itself?
    extra_event_keys = set(event.keys()) - {"eventId", "type", "payload"}
    if extra_event_keys:
        findings.append(f"EXTRA EVENT KEYS: {extra_event_keys}")

    # 3. Analyze message payloads
    if event_type in ("newMessage", "editedMessage", "pinnedMessage", "unpinnedMessage"):
        extra_msg_fields = set(payload.keys()) - KNOWN_MESSAGE_FIELDS
        if extra_msg_fields:
            findings.append(f"EXTRA MESSAGE FIELDS: {extra_msg_fields}")

        # Analyze parts
        for i, part in enumerate(payload.get("parts", [])):
            ptype = part.get("type", "")
            if ptype and ptype not in KNOWN_PART_TYPES:
                findings.append(f"UNKNOWN PART TYPE [{i}]: '{ptype}'")
            ppayload = part.get("payload", {})
            if isinstance(ppayload, dict):
                findings.append(f"PART [{i}] type='{ptype}' keys={set(ppayload.keys())}")
            elif isinstance(ppayload, list):
                findings.append(f"PART [{i}] type='{ptype}' payload_is_list len={len(ppayload)}")

    # 4. Analyze callback query
    if event_type == "callbackQuery":
        extra_cb_fields = set(payload.keys()) - KNOWN_CALLBACK_FIELDS
        if extra_cb_fields:
            findings.append(f"EXTRA CALLBACK FIELDS: {extra_cb_fields}")

    # 5. Analyze member events
    if event_type in ("newChatMembers", "leftChatMembers"):
        findings.append(f"MEMBER EVENT KEYS: {set(payload.keys())}")

    # 6. Analyze changedChatInfo
    if event_type == "changedChatInfo":
        findings.append(f"CHANGED_CHAT_INFO KEYS: {set(payload.keys())}")

    return {
        "_type": "ANALYSIS",
        "event_type": event_type,
        "eventId": event.get("eventId"),
        "findings": findings,
        "payload_keys": list(payload.keys()) if isinstance(payload, dict) else str(type(payload)),
    }


# ── Human-readable echo ───────────────────────────────────────────────────

def describe_event(event: dict[str, Any]) -> str:
    """Build a human-readable summary to echo back to the tester."""
    etype = event.get("type", "?")
    payload = event.get("payload", {})
    lines: list[str] = [f"Event: {etype}"]

    if etype in ("newMessage", "editedMessage"):
        text = payload.get("text", "")
        if text:
            lines.append(f"Text: {text[:200]}")
        parts = payload.get("parts", [])
        if parts:
            part_summary = ", ".join(
                f"{p.get('type', '?')}" for p in parts
            )
            lines.append(f"Parts ({len(parts)}): {part_summary}")
        fmt = payload.get("format")
        if fmt:
            lines.append(f"Format: {json.dumps(fmt, ensure_ascii=False)[:300]}")
        from_user = payload.get("from", {})
        if from_user:
            lines.append(f"From: {from_user.get('firstName', '')} {from_user.get('lastName', '')} [{from_user.get('userId', '')}]")

    elif etype == "callbackQuery":
        lines.append(f"CallbackData: {payload.get('callbackData', '')}")
        lines.append(f"QueryId: {payload.get('queryId', '')}")

    elif etype == "deletedMessage":
        lines.append(f"MsgId: {payload.get('msgId', '')}")

    elif etype in ("pinnedMessage", "unpinnedMessage"):
        lines.append(f"MsgId: {payload.get('msgId', '')}")
        text = payload.get("text", "")
        if text:
            lines.append(f"Text: {text[:100]}")

    elif etype in ("newChatMembers", "leftChatMembers"):
        members = payload.get("newMembers", payload.get("leftMembers", payload.get("members", [])))
        if isinstance(members, list):
            for m in members:
                lines.append(f"  User: {m.get('userId', '?')}")

    elif etype == "changedChatInfo":
        for k, v in payload.items():
            lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)[:200]}")

    else:
        # Unknown — dump all keys
        lines.append(f"Keys: {list(payload.keys())}")
        for k, v in payload.items():
            lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False, default=str)[:200]}")

    # Extra keys detection
    extra_event_keys = set(event.keys()) - {"eventId", "type", "payload"}
    if extra_event_keys:
        lines.append(f"EXTRA KEYS at event level: {extra_event_keys}")

    return "\n".join(lines)


# ── Bot commands ───────────────────────────────────────────────────────────

async def handle_command(
    client: DiagnosticClient,
    chat_id: str,
    text: str,
    payload: dict[str, Any],
) -> None:
    """Handle /commands for interactive testing."""
    cmd = text.strip().split()[0].lower()

    if cmd == "/start":
        builder = InlineKeyboardBuilder()
        builder.button(text="Button A", callback_data="diag_a")
        builder.button(text="Button B", callback_data="diag_b")
        builder.button(text="Alert btn", callback_data="diag_alert")
        builder.button(text="URL btn", url="https://example.com")
        builder.adjust(2, 2)

        await client.send_text(
            chat_id,
            "Diagnostic bot ready.\n\n"
            "I log ALL raw events to diagnostic_log.jsonl.\n\n"
            "Try:\n"
            "- Send any text, image, file, sticker, voice\n"
            "- Forward a message\n"
            "- Reply to a message\n"
            "- React to a message\n"
            "- Create a poll\n"
            "- Pin/unpin a message\n"
            "- Add/remove users from group\n"
            "- Change chat title/description\n"
            "- Click the buttons below\n"
            "- /info — chat info\n"
            "- /admins — chat admins\n"
            "- /members — chat members\n"
            "- /me — bot info\n"
            "- /stats — logging stats",
            inlineKeyboardMarkup=builder.as_json(),
        )

    elif cmd == "/info":
        data = await client.get_chat_info(chat_id)
        await client.send_text(chat_id, f"Chat info:\n{json.dumps(data, ensure_ascii=False, indent=2)[:4000]}")

    elif cmd == "/admins":
        data = await client.get_chat_admins(chat_id)
        await client.send_text(chat_id, f"Admins:\n{json.dumps(data, ensure_ascii=False, indent=2)[:4000]}")

    elif cmd == "/members":
        data = await client.get_chat_members(chat_id)
        await client.send_text(chat_id, f"Members:\n{json.dumps(data, ensure_ascii=False, indent=2)[:4000]}")

    elif cmd == "/me":
        data = await client.get_me()
        await client.send_text(chat_id, f"Bot info:\n{json.dumps(data, ensure_ascii=False, indent=2)[:4000]}")

    elif cmd == "/stats":
        if LOG_FILE.exists():
            with open(LOG_FILE, encoding="utf-8") as fh:
                line_count = sum(1 for _ in fh)
            size_kb = LOG_FILE.stat().st_size / 1024
            # Count event types
            type_counts: dict[str, int] = {}
            with open(LOG_FILE, encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        if obj.get("_type") == "RAW_EVENT":
                            et = obj.get("type", "?")
                            type_counts[et] = type_counts.get(et, 0) + 1
                    except Exception:
                        pass
            stats_text = (
                f"Log file: {LOG_FILE.name}\n"
                f"Lines: {line_count}\n"
                f"Size: {size_kb:.1f} KB\n\n"
                f"Event types captured:\n"
            )
            for et, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
                stats_text += f"  {et}: {cnt}\n"
            await client.send_text(chat_id, stats_text)
        else:
            await client.send_text(chat_id, "No log file yet.")


# ── Main loop ──────────────────────────────────────────────────────────────

async def main() -> None:
    client = DiagnosticClient(token=TOKEN, api_url=API_URL)

    # Log session start
    write_log({
        "_type": "SESSION_START",
        "api_url": API_URL,
        "log_file": str(LOG_FILE),
    })

    # Get bot info
    me = await client.get_me()
    bot_id = me.get("userId", me.get("nick", "?"))
    log.info("Bot started: %s", bot_id)
    write_log({"_type": "BOT_INFO", "data": me})

    running = True

    def stop() -> None:
        nonlocal running
        running = False
        log.info("Stopping...")

    # Graceful shutdown on Ctrl+C
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop)

    log.info("Diagnostic bot polling... (log → %s)", LOG_FILE)
    log.info("Send /start to the bot to begin testing")

    # Skip old events on startup
    await client.get_events(poll_time=0)
    log.info("Skipped old events, lastEventId=%d", client._last_event_id)

    while running:
        try:
            events = await client.get_events(poll_time=30)
        except asyncio.CancelledError:
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception("Polling error: %s", e)
            write_log({"_type": "POLL_ERROR", "error": str(e)})
            await asyncio.sleep(2)
            continue

        for event in events:
            # Analyze and log findings
            analysis = analyze_event(event)
            if analysis["findings"]:
                write_log(analysis)
                for finding in analysis["findings"]:
                    log.info("FINDING: %s", finding)

            event_type = event.get("type", "")
            payload = event.get("payload", {})
            chat_id = ""

            # Extract chat_id from various event structures
            chat = payload.get("chat", {})
            if isinstance(chat, dict):
                chat_id = chat.get("chatId", "")
            if not chat_id and "message" in payload:
                msg = payload.get("message", {})
                if isinstance(msg, dict):
                    chat_id = msg.get("chat", {}).get("chatId", "")

            # Handle events
            try:
                if event_type in ("newMessage", "editedMessage"):
                    text = payload.get("text", "") or ""

                    # Handle commands
                    if text.startswith("/"):
                        await handle_command(client, chat_id, text, payload)
                    else:
                        # Echo back what we received
                        summary = describe_event(event)
                        if chat_id:
                            await client.send_text(
                                chat_id,
                                f"Logged {event_type}:\n\n{summary}",
                            )

                    # If message has file parts, try to get file info
                    for part in payload.get("parts", []):
                        pp = part.get("payload", {})
                        if isinstance(pp, dict) and "fileId" in pp:
                            file_info = await client.get_file_info(pp["fileId"])
                            write_log({
                                "_type": "FILE_INFO",
                                "fileId": pp["fileId"],
                                "data": file_info,
                            })

                elif event_type == "callbackQuery":
                    query_id = payload.get("queryId", "")
                    cb_data = payload.get("callbackData", "")

                    # Answer the callback
                    show_alert = cb_data == "diag_alert"
                    await client.answer_callback(
                        query_id,
                        text=f"Got callback: {cb_data}",
                        show_alert=show_alert,
                    )

                    # Also echo in chat
                    if chat_id:
                        summary = describe_event(event)
                        await client.send_text(
                            chat_id,
                            f"Logged callbackQuery:\n\n{summary}",
                        )

                elif event_type in ("deletedMessage", "pinnedMessage", "unpinnedMessage",
                                     "newChatMembers", "leftChatMembers", "changedChatInfo"):
                    if chat_id:
                        summary = describe_event(event)
                        await client.send_text(
                            chat_id,
                            f"Logged {event_type}:\n\n{summary}",
                        )

                else:
                    # UNKNOWN EVENT TYPE — this is the most interesting
                    log.warning("UNKNOWN EVENT TYPE: %s", event_type)
                    if chat_id:
                        await client.send_text(
                            chat_id,
                            f"UNKNOWN EVENT TYPE: {event_type}\n\n"
                            f"Full payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)[:3800]}",
                        )

            except Exception as e:
                log.exception("Error handling event %s: %s", event_type, e)
                write_log({
                    "_type": "HANDLER_ERROR",
                    "event_type": event_type,
                    "error": str(e),
                    "error_type": type(e).__name__,
                })

    write_log({"_type": "SESSION_END"})
    await client.close()
    log.info("Stopped. Log saved to %s", LOG_FILE)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted")
