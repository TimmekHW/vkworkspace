from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, BinaryIO

import httpx

from vkworkspace.exceptions import VKTeamsAPIError
from vkworkspace.types.chat import ChatInfo
from vkworkspace.types.event import Update
from vkworkspace.types.file import File
from vkworkspace.types.input_file import InputFile
from vkworkspace.types.response import APIResponse
from vkworkspace.types.thread import Thread, ThreadSubscribers
from vkworkspace.types.user import BotInfo, ChatMember, User

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Simple rate limiter based on minimum interval between requests.

    Usage::

        limiter = RateLimiter(rate=5)  # max 5 requests/sec
        await limiter.acquire()        # blocks if too fast
    """

    def __init__(self, rate: float) -> None:
        self.rate = rate
        self.interval = 1.0 / rate
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self._last_request = time.monotonic()


class Bot:
    """
    VK Teams Bot API client.

    All methods are async and use httpx.AsyncClient under the hood.

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
        # Your other httpx clients (e.g. requests to 83.166.254.26:8000) are NOT affected.
    """

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.icq.net/bot/v1",
        timeout: float = 30.0,
        poll_time: int = 60,
        rate_limit: float | None = None,
        proxy: str | None = None,
    ) -> None:
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.poll_time = poll_time
        self.rate_limit = rate_limit
        self.proxy = proxy
        self._rate_limiter: RateLimiter | None = (
            RateLimiter(rate_limit) if rate_limit else None
        )
        self._session: httpx.AsyncClient | None = None
        self._last_event_id: int = 0

    async def get_session(self) -> httpx.AsyncClient:
        if self._session is None or self._session.is_closed:
            self._session = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.timeout + self.poll_time,
                    connect=10.0,
                ),
                follow_redirects=True,
                proxy=self.proxy,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.is_closed:
            await self._session.aclose()

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
        if self._rate_limiter:
            await self._rate_limiter.acquire()

        session = await self.get_session()
        url = f"{self.api_url}/{endpoint}"

        if files:
            resp = await session.post(url, data=params, files=files)
        else:
            resp = await session.post(url, data=params)

        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        if data.get("ok") is False:
            raise VKTeamsAPIError(
                method=endpoint,
                message=data.get("description", "Unknown error"),
            )

        return data

    @staticmethod
    def _keyboard_json(keyboard: Any) -> str | None:
        if keyboard is None:
            return None
        if isinstance(keyboard, str):
            return keyboard
        if isinstance(keyboard, list):
            return json.dumps(keyboard, ensure_ascii=False)
        if hasattr(keyboard, "as_json"):
            return keyboard.as_json()
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
            return format_.to_json()
        return None

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
        """Long-poll for events. ``events/get``"""
        eid = last_event_id if last_event_id is not None else self._last_event_id
        pt = poll_time if poll_time is not None else self.poll_time

        data = await self._request(
            "events/get",
            self._params(pollTime=pt, lastEventId=eid),
        )

        events: list[Update] = []
        for raw in data.get("events", []):
            update = Update.model_validate(raw)
            events.append(update)
            if update.event_id > self._last_event_id:
                self._last_event_id = update.event_id

        return events

    # ── Messages ──────────────────────────────────────────────────────

    TEXT_LENGTH_WARNING = 4096

    async def send_text(
        self,
        chat_id: str,
        text: str,
        reply_msg_id: str | None = None,
        forward_chat_id: str | None = None,
        forward_msg_id: str | None = None,
        inline_keyboard_markup: Any = None,
        parse_mode: str | None = None,
        format_: dict[str, Any] | Any | None = None,
    ) -> APIResponse:
        """Send text message. ``messages/sendText``"""
        if len(text) > self.TEXT_LENGTH_WARNING:
            logger.warning(
                "Text length %d exceeds %d chars — "
                "may cause UI lag or be rejected by the server",
                len(text),
                self.TEXT_LENGTH_WARNING,
            )
        data = await self._request(
            "messages/sendText",
            self._params(
                chatId=chat_id,
                text=text,
                replyMsgId=reply_msg_id,
                forwardChatId=forward_chat_id,
                forwardMsgId=forward_msg_id,
                inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
                parseMode=parse_mode,
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
        parse_mode: str | None = None,
        format_: dict[str, Any] | Any | None = None,
    ) -> APIResponse:
        """Edit message text. ``messages/editText``"""
        if len(text) > self.TEXT_LENGTH_WARNING:
            logger.warning(
                "Text length %d exceeds %d chars — "
                "may cause UI lag or be rejected by the server",
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
                parseMode=parse_mode,
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
        reply_msg_id: str | None = None,
        forward_chat_id: str | None = None,
        forward_msg_id: str | None = None,
        inline_keyboard_markup: Any = None,
        parse_mode: str | None = None,
        format_: dict[str, Any] | Any | None = None,
    ) -> APIResponse:
        """Send file. ``messages/sendFile``"""
        params = self._params(
            chatId=chat_id,
            fileId=file_id,
            caption=caption,
            replyMsgId=reply_msg_id,
            forwardChatId=forward_chat_id,
            forwardMsgId=forward_msg_id,
            inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
            parseMode=parse_mode,
            format=self._format_json(format_),
        )
        files_dict = self._file_payload(file)
        data = await self._request("messages/sendFile", params, files_dict)
        return APIResponse.model_validate(data)

    async def send_voice(
        self,
        chat_id: str,
        file_id: str | None = None,
        file: InputFile | BinaryIO | None = None,
        reply_msg_id: str | None = None,
        forward_chat_id: str | None = None,
        forward_msg_id: str | None = None,
        inline_keyboard_markup: Any = None,
    ) -> APIResponse:
        """Send voice message. ``messages/sendVoice``"""
        params = self._params(
            chatId=chat_id,
            fileId=file_id,
            replyMsgId=reply_msg_id,
            forwardChatId=forward_chat_id,
            forwardMsgId=forward_msg_id,
            inlineKeyboardMarkup=self._keyboard_json(inline_keyboard_markup),
        )
        files_dict = self._file_payload(file)
        data = await self._request("messages/sendVoice", params, files_dict)
        return APIResponse.model_validate(data)

    async def answer_callback_query(
        self,
        query_id: str,
        text: str = "",
        show_alert: bool = False,
        url: str | None = None,
    ) -> APIResponse:
        """Answer callback query. ``messages/answerCallbackQuery``"""
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

    async def get_chat_admins(self, chat_id: str) -> list[ChatMember]:
        """Get chat admins. ``chats/getAdmins``"""
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

    async def set_chat_avatar(
        self,
        chat_id: str,
        file: InputFile | BinaryIO,
    ) -> APIResponse:
        """Set chat avatar. ``chats/avatar/set``"""
        params = self._params(chatId=chat_id)
        files_dict = self._file_payload(file)
        data = await self._request("chats/avatar/set", params, files_dict)
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

    # ── Threads ───────────────────────────────────────────────────────

    async def threads_get_subscribers(
        self,
        thread_id: str,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> ThreadSubscribers:
        """Get thread subscribers. ``threads/subscribers/get``"""
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
        """Toggle thread autosubscribe. ``threads/autosubscribe``"""
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
        """Create thread from message. ``threads/add``"""
        data = await self._request(
            "threads/add",
            self._params(chatId=chat_id, msgId=msg_id),
        )
        return Thread.model_validate(data)
