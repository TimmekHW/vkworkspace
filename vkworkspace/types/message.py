from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from .base import VKTeamsObject
from .chat import Chat
from .user import Contact

if TYPE_CHECKING:
    from vkworkspace.enums import ParseMode

_UNSET: Any = object()


class Part(VKTeamsObject):
    type: str = ""
    payload: Any = Field(default_factory=dict)


class Message(VKTeamsObject):
    msg_id: str = Field(default="", alias="msgId")
    chat: Chat = Field(default_factory=lambda: Chat(chatId="", type=""))
    from_user: Contact | None = Field(default=None, alias="from")
    text: str | None = None
    timestamp: int | None = None
    edited_timestamp: int | None = Field(default=None, alias="editedTimestamp")
    format: dict[str, Any] | None = None
    parts: list[Part] = Field(default_factory=list)

    async def answer(
        self,
        text: str,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Any:
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        return await self.bot.send_text(
            chat_id=self.chat.chat_id,
            text=text,
            **kwargs,
        )

    async def reply(
        self,
        text: str,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Any:
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        return await self.bot.send_text(
            chat_id=self.chat.chat_id,
            text=text,
            reply_msg_id=self.msg_id,
            **kwargs,
        )

    async def delete(self) -> Any:
        return await self.bot.delete_messages(
            chat_id=self.chat.chat_id,
            msg_id=self.msg_id,
        )

    async def edit_text(
        self,
        text: str,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Any:
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        return await self.bot.edit_text(
            chat_id=self.chat.chat_id,
            msg_id=self.msg_id,
            text=text,
            **kwargs,
        )

    async def pin(self) -> Any:
        return await self.bot.pin_message(
            chat_id=self.chat.chat_id,
            msg_id=self.msg_id,
        )

    async def unpin(self) -> Any:
        return await self.bot.unpin_message(
            chat_id=self.chat.chat_id,
            msg_id=self.msg_id,
        )

    async def answer_file(
        self,
        file_id: str | None = None,
        file: Any = None,
        caption: str | None = None,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Any:
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        return await self.bot.send_file(
            chat_id=self.chat.chat_id,
            file_id=file_id,
            file=file,
            caption=caption,
            **kwargs,
        )

    async def answer_voice(
        self,
        file_id: str | None = None,
        file: Any = None,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Any:
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        return await self.bot.send_voice(
            chat_id=self.chat.chat_id,
            file_id=file_id,
            file=file,
            **kwargs,
        )
