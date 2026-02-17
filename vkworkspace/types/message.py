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
    """A single part of a message (mention, reply, forward, file, sticker, etc.).

    Use ``.as_mention``, ``.as_reply``, ``.as_forward``, ``.as_file``
    properties to parse the raw payload into typed objects.
    """

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
    """Incoming message from VK Teams.

    This is the main object you work with in ``@router.message()`` handlers.

    Key methods:
        - ``.answer(text)`` — send a reply to the same chat
        - ``.reply(text)`` — reply with quote (shows original message)
        - ``.edit_text(text)`` — edit this message's text
        - ``.delete()`` — delete this message
        - ``.pin()`` / ``.unpin()`` — pin/unpin in chat
        - ``.answer_file(file=...)`` — send a file to the same chat
        - ``.answer_voice(file=...)`` — send a voice message

    Key properties:
        - ``.text`` — message text (``None`` if no text)
        - ``.chat`` — chat where the message was sent
        - ``.from_user`` — who sent the message
        - ``.mentions`` — list of @mentions
        - ``.reply_to`` — original message if this is a reply
        - ``.forwards`` — list of forwarded messages
        - ``.files`` — list of file attachments

    Example::

        @router.message(Command("start"))
        async def start(message: Message):
            await message.answer("Hello!")
    """

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
        """Send a text message to the same chat.

        If this message is from a thread, the reply stays in the same thread.

        Args:
            text: Message text.
            parse_mode: ``"HTML"`` / ``"MarkdownV2"`` / ``None``.
            inline_keyboard_markup: Inline keyboard.
            **kwargs: Extra args passed to ``bot.send_text()``.

        Example::

            await message.answer("Got it!")
            await message.answer("*Bold*", parse_mode="MarkdownV2")
        """
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
        """Reply with a quote — shows the original message above the response.

        Args:
            text: Reply text.
            parse_mode: ``"HTML"`` / ``"MarkdownV2"`` / ``None``.
            inline_keyboard_markup: Inline keyboard.

        Example::

            await message.reply("I see your message!")
        """
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
        """Delete this message from the chat."""
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
        """Edit the text of this message.

        Args:
            text: New message text.
            parse_mode: ``"HTML"`` / ``"MarkdownV2"`` / ``None``.
            inline_keyboard_markup: Updated inline keyboard.

        Example::

            await message.edit_text("Updated text!")
        """
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
        """Pin this message in the chat."""
        return await self.bot.pin_message(
            chat_id=self.chat.chat_id,
            msg_id=self.msg_id,
        )

    async def unpin(self) -> Any:
        """Unpin this message from the chat."""
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
        """Send a file/image to the same chat.

        Args:
            file_id: ID of a previously uploaded file (no re-upload).
            file: ``InputFile`` or open ``BinaryIO`` to upload.
            caption: Text caption below the file.

        Example::

            await message.answer_file(file=InputFile("report.pdf"), caption="Here!")
        """
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
        """Send a voice message to the same chat.

        Recommended format: OGG/Opus. Convert with
        ``vkworkspace.utils.voice.convert_to_ogg_opus()`` if needed.

        Args:
            file_id: ID of a previously uploaded voice.
            file: ``InputFile`` with OGG/Opus data.

        Example::

            ogg = convert_to_ogg_opus("audio.mp3")
            await message.answer_voice(file=InputFile(ogg, filename="voice.ogg"))
        """
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        return await self.bot.send_voice(
            chat_id=self.chat.chat_id,
            file_id=file_id,
            file=file,
            **kwargs,
        )
