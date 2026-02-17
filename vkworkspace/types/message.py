from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from .base import VKTeamsObject
from .chat import Chat
from .user import Contact

if TYPE_CHECKING:
    from vkworkspace.enums import ParseMode

_UNSET: Any = object()


# ── Format spans (offset/length ranges in text) ──────────────────

class FormatSpan(VKTeamsObject):
    """A single formatting span: offset + length within the text."""

    offset: int = 0
    length: int = 0
    url: str | None = None  # only for "link" spans


class MessageFormat(VKTeamsObject):
    """Parsed ``format`` field describing text formatting ranges."""

    bold: list[FormatSpan] = Field(default_factory=list)
    italic: list[FormatSpan] = Field(default_factory=list)
    underline: list[FormatSpan] = Field(default_factory=list)
    strikethrough: list[FormatSpan] = Field(default_factory=list)
    link: list[FormatSpan] = Field(default_factory=list)
    mention: list[FormatSpan] = Field(default_factory=list)
    inline_code: list[FormatSpan] = Field(default_factory=list, alias="inlineCode")
    pre: list[FormatSpan] = Field(default_factory=list)
    ordered_list: list[FormatSpan] = Field(default_factory=list, alias="orderedList")
    unordered_list: list[FormatSpan] = Field(
        default_factory=list, alias="unorderedList"
    )
    quote: list[FormatSpan] = Field(default_factory=list)


# ── Thread parent (parent_topic) ─────────────────────────────────

class ParentMessage(VKTeamsObject):
    """Reference to the root message of a thread (``parent_topic``).

    Present in incoming events when the message was sent inside a thread.
    Pass it back via ``send_text(parent_topic=...)`` to reply in the same thread.

    From Go lib: ``ParentMessage{ChatID, MsgID int64, Type}`` json:"parent_topic"
    """

    chat_id: str = Field(default="", alias="chatId")
    message_id: int = Field(default=0, alias="messageId")
    type: str = ""


# ── Message parts (mention, reply, forward, file, …) ─────────────

class MentionPayload(VKTeamsObject):
    """Payload for ``parts[].type == "mention"``."""

    user_id: str = Field(default="", alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None


class ReplyMessagePayload(VKTeamsObject):
    """Inner message inside a reply/forward payload."""

    msg_id: str = Field(default="", alias="msgId")
    text: str | None = None
    timestamp: int | None = None
    from_user: Contact | None = Field(default=None, alias="from")


class ReplyPayload(VKTeamsObject):
    """Payload for ``parts[].type == "reply"``."""

    message: ReplyMessagePayload = Field(
        default_factory=lambda: ReplyMessagePayload(msgId=""),
    )


class ForwardPayload(VKTeamsObject):
    """Payload for ``parts[].type == "forward"``."""

    message: ReplyMessagePayload = Field(
        default_factory=lambda: ReplyMessagePayload(msgId=""),
    )


class FilePayload(VKTeamsObject):
    """Payload for ``parts[].type == "file"``."""

    file_id: str = Field(default="", alias="fileId")
    type: str = ""  # "image", "audio", "video", etc.
    caption: str | None = None


class Part(VKTeamsObject):
    type: str = ""
    payload: Any = Field(default_factory=dict)

    @property
    def as_mention(self) -> MentionPayload | None:
        """Parse payload as MentionPayload if type == "mention"."""
        if self.type != "mention":
            return None
        data = self.payload if isinstance(self.payload, dict) else {}
        return MentionPayload.model_validate(data)

    @property
    def as_reply(self) -> ReplyPayload | None:
        """Parse payload as ReplyPayload if type == "reply"."""
        if self.type != "reply":
            return None
        data = self.payload if isinstance(self.payload, dict) else {}
        return ReplyPayload.model_validate(data)

    @property
    def as_forward(self) -> ForwardPayload | None:
        """Parse payload as ForwardPayload if type == "forward"."""
        if self.type != "forward":
            return None
        data = self.payload if isinstance(self.payload, dict) else {}
        return ForwardPayload.model_validate(data)

    @property
    def as_file(self) -> FilePayload | None:
        """Parse payload as FilePayload if type == "file"."""
        if self.type != "file":
            return None
        data = self.payload if isinstance(self.payload, dict) else {}
        return FilePayload.model_validate(data)


class Message(VKTeamsObject):
    msg_id: str = Field(default="", alias="msgId")
    chat: Chat = Field(default_factory=lambda: Chat(chatId="", type=""))
    from_user: Contact | None = Field(default=None, alias="from")
    text: str | None = None
    timestamp: int | None = None
    edited_timestamp: int | None = Field(default=None, alias="editedTimestamp")
    format: MessageFormat | None = None
    parts: list[Part] = Field(default_factory=list)
    parent_topic: ParentMessage | None = Field(default=None, alias="parent_topic")

    @property
    def is_thread_message(self) -> bool:
        """True if this message was sent inside a thread."""
        return self.parent_topic is not None

    # ── Convenience accessors for parts ───────────────────────────

    @property
    def mentions(self) -> list[MentionPayload]:
        """All mention parts as typed objects."""
        return [m for p in self.parts if (m := p.as_mention) is not None]

    @property
    def reply_to(self) -> ReplyMessagePayload | None:
        """Original message if this is a reply, else None."""
        for p in self.parts:
            if r := p.as_reply:
                return r.message
        return None

    @property
    def forwards(self) -> list[ReplyMessagePayload]:
        """All forwarded messages as typed objects."""
        return [
            f.message for p in self.parts if (f := p.as_forward) is not None
        ]

    @property
    def files(self) -> list[FilePayload]:
        """All file attachments as typed objects."""
        return [f for p in self.parts if (f := p.as_file) is not None]

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
        # If this message is from a thread, reply stays in the same thread
        if self.parent_topic is not None and "parent_topic" not in kwargs:
            kwargs["parent_topic"] = self.parent_topic
        return await self.bot.send_text(
            chat_id=self.chat.chat_id,
            text=text,
            **kwargs,
        )

    async def answer_thread(
        self,
        text: str,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Create a thread under this message and post *text* into it.

        If this message already lives in a thread, posts there instead.
        """
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        pt = self.parent_topic
        if pt is None:
            # Build a parent_topic pointing at this message
            pt = ParentMessage(
                chatId=self.chat.chat_id,
                messageId=int(self.msg_id) if self.msg_id.isdigit() else 0,
                type="thread",
            )
        return await self.bot.send_text(
            chat_id=self.chat.chat_id,
            text=text,
            parent_topic=pt,
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
