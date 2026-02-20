from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from .base import VKTeamsObject
from .chat import Chat
from .user import Contact

if TYPE_CHECKING:
    from vkworkspace.enums import ChatAction, ParseMode
    from vkworkspace.utils.actions import ChatActionSender

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
    unordered_list: list[FormatSpan] = Field(default_factory=list, alias="unorderedList")
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
    format: MessageFormat | None = None  # present when quoted message has formatting


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

    Note:
        Methods that send messages (``answer``, ``reply``, ``answer_file``, etc.)
        return a partially-populated :class:`Message`. VK Teams API only returns
        ``msgId`` on send — so ``timestamp``, ``from_user``, and ``parts`` will
        be ``None`` / empty in the returned object. Only ``msg_id`` and ``chat``
        are guaranteed. Use ``.delete()`` / ``.edit_text()`` freely — they only
        need ``msg_id`` and ``chat``.

    Key properties:
        - ``.text`` — message text (``None`` for files-with-caption and forwards)
        - ``.caption`` — file caption (``None`` if no caption)
        - ``.content`` — ``.text`` or ``.caption``, whichever is set
        - ``.chat`` — chat where the message was sent (**thread's own chat** for thread messages)
        - ``.from_user`` — who sent the message
        - ``.is_edited`` — ``True`` if the message was edited
        - ``.is_thread_message`` — ``True`` if sent inside a thread or channel comment
        - ``.thread_root_chat_id`` — original chat ID (for thread/comment messages)
        - ``.thread_root_message_id`` — root message ID as int (for thread/comment messages)
        - ``.mentions`` — list of @mentions
        - ``.reply_to`` — original message if this is a reply
        - ``.forwards`` — list of forwarded messages
        - ``.files`` — list of file attachments
        - ``.sticker`` — sticker attachment or ``None``
        - ``.voice`` — voice attachment or ``None``

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
        """``True`` if this message was sent inside a thread.

        Thread messages arrive as ``newMessage`` events with ``parent_topic``
        set.  Their ``chat.chat_id`` is the **thread's own chat ID** (not the
        original group/channel chat).  Use ``thread_root_chat_id`` and
        ``thread_root_message_id`` to reach the root message.

        .. note:: **Channel comments are thread messages.**
            When a bot is a member of a channel, it receives all comments
            to channel posts as thread messages — without any subscription.
            The comment's ``thread_root_chat_id`` will be the channel's chat ID.

        Example::

            @router.message(F.is_thread_message)
            async def on_thread_msg(message: Message):
                root_chat = message.thread_root_chat_id
                root_msg  = message.thread_root_message_id
                await message.answer("Вижу тред!")   # replies into the thread
        """
        return self.parent_topic is not None

    @property
    def thread_root_chat_id(self) -> str | None:
        """Chat ID of the original chat where the thread root message was posted.

        ``None`` if this message is not in a thread.
        For channel comments this equals the channel's chat ID.
        """
        return self.parent_topic.chat_id if self.parent_topic else None

    @property
    def thread_root_message_id(self) -> int | None:
        """Message ID (int) of the thread root message in the original chat.

        ``None`` if this message is not in a thread.
        """
        return self.parent_topic.message_id if self.parent_topic else None

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
        return [f.message for p in self.parts if (f := p.as_forward) is not None]

    @property
    def files(self) -> list[FilePayload]:
        """All file attachments as typed objects."""
        return [f for p in self.parts if (f := p.as_file) is not None]

    @property
    def caption(self) -> str | None:
        """Caption of a file/image message, or ``None`` if absent.

        VK Teams omits the top-level ``text`` field when a **single** file has a
        caption — the caption lives only in ``parts[0].payload.caption``.
        This property normalises that so you don't have to dig into parts.

        Note:
            When **multiple** files are sent in one message, VK Teams puts all
            file URLs followed by the caption into ``text`` (no clean separation).
            In that case this property returns ``None``; use ``message.text``
            directly and strip the URLs manually if needed.

        Example::

            @router.message(F.caption)
            async def on_photo(message: Message):
                print(message.caption)   # "фото с текстом"
        """
        for part in self.parts:
            if f := part.as_file:
                return f.caption
        return None

    @property
    def content(self) -> str | None:
        """Message text — falls back to ``caption`` if ``text`` is ``None``.

        Handy for handlers that handle both plain text and file-with-caption.

        Example::

            @router.message(F.content)
            async def on_any_text(message: Message):
                print(message.content)  # text or caption, whichever is set
        """
        return self.text or self.caption

    @property
    def is_edited(self) -> bool:
        """``True`` if this message was edited (``editedTimestamp`` is set).

        .. note:: **VK Teams quirk — ghost delete event in private chats.**
            When a message is deleted in a **private** chat, VK Teams sends two
            events: a proper ``deletedMessage`` event *and* a ghost ``newMessage``
            event with the same ``msgId``, no ``text``, and ``editedTimestamp``
            set.  That ghost event lands in ``@router.message()`` handlers with
            ``is_edited=True`` and ``text=None``.

            Most handlers are unaffected (``F.text``, ``Command()``, etc. do not
            match ``None``).  If you use bare ``@router.message()`` without any
            filters, guard against it::

                @router.message(F.is_edited == False)  # skip ghost events
                async def on_msg(message: Message): ...

        Example::

            @router.edited_message(F.is_edited)
            async def on_edit(message: Message):
                print("edited at", message.edited_timestamp)
        """
        return self.edited_timestamp is not None

    @property
    def sticker(self) -> FilePayload | None:
        """Sticker attachment, or ``None`` if not a sticker message.

        Example::

            @router.message(F.sticker)
            async def on_sticker(message: Message):
                s = message.sticker
                print(s.file_id)   # sticker file ID
        """
        for part in self.parts:
            if part.type == "sticker":
                data = part.payload if isinstance(part.payload, dict) else {}
                return FilePayload.model_validate(data)
        return None

    @property
    def voice(self) -> FilePayload | None:
        """Voice message attachment, or ``None`` if not a voice message.

        Example::

            @router.message(F.voice)
            async def on_voice(message: Message):
                v = message.voice
                await bot.get_file_info(v.file_id)
        """
        for part in self.parts:
            if part.type == "voice":
                data = part.payload if isinstance(part.payload, dict) else {}
                return FilePayload.model_validate(data)
        return None

    async def answer(
        self,
        text: str,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Message:
        """Send a text message to the same chat.

        If this message is from a thread, the reply stays in the same thread.

        Returns a bound :class:`Message` — you can call ``.delete()``,
        ``.edit_text()``, etc. on it directly.

        Args:
            text: Message text.
            parse_mode: ``"HTML"`` / ``"MarkdownV2"`` / ``None``.
            inline_keyboard_markup: Inline keyboard.
            **kwargs: Extra args passed to ``bot.send_text()``.

        Example::

            await message.answer("Got it!")
            await message.answer("*Bold*", parse_mode="MarkdownV2")

            # Delete the sent message after a delay:
            sent = await message.answer("I will vanish in 5 seconds")
            await asyncio.sleep(5)
            await sent.delete()

        Note:
            VK Teams API returns only ``msgId`` on send. The returned
            :class:`Message` has ``msg_id`` and ``chat`` set; ``timestamp``,
            ``from_user``, and ``parts`` are ``None`` / empty — VK Teams API
            limitation, not a bug.
        """
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        # If this message is from a thread, reply stays in the same thread
        if self.parent_topic is not None and "parent_topic" not in kwargs:
            kwargs["parent_topic"] = self.parent_topic
        resp = await self.bot.send_text(
            chat_id=self.chat.chat_id,
            text=text,
            **kwargs,
        )
        sent = Message.model_construct(msg_id=resp.msg_id or "", chat=self.chat, text=text)
        sent.set_bot(self.bot)
        return sent

    async def answer_thread(
        self,
        text: str,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Message:
        """Create a thread under this message and post *text* into it.

        If this message already lives in a thread, posts there instead.
        Returns a bound :class:`Message` — supports ``.delete()``, ``.edit_text()``.

        Note:
            VK Teams API returns only ``msgId`` on send. ``timestamp``,
            ``from_user``, and ``parts`` will be ``None`` / empty.
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
        resp = await self.bot.send_text(
            chat_id=self.chat.chat_id,
            text=text,
            parent_topic=pt,
            **kwargs,
        )
        sent = Message.model_construct(msg_id=resp.msg_id or "", chat=self.chat, text=text)
        sent.set_bot(self.bot)
        return sent

    async def reply(
        self,
        text: str,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Message:
        """Reply with a quote — shows the original message above the response.

        Returns a bound :class:`Message` — supports ``.delete()``, ``.edit_text()``.

        Args:
            text: Reply text.
            parse_mode: ``"HTML"`` / ``"MarkdownV2"`` / ``None``.
            inline_keyboard_markup: Inline keyboard.

        Example::

            await message.reply("I see your message!")

        Note:
            VK Teams API returns only ``msgId`` on send. ``timestamp``,
            ``from_user``, and ``parts`` will be ``None`` / empty.
        """
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        resp = await self.bot.send_text(
            chat_id=self.chat.chat_id,
            text=text,
            reply_msg_id=self.msg_id,
            **kwargs,
        )
        sent = Message.model_construct(msg_id=resp.msg_id or "", chat=self.chat, text=text)
        sent.set_bot(self.bot)
        return sent

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

    async def answer_chat_action(
        self,
        action: ChatAction | str | None = None,
    ) -> Any:
        """Send a one-shot chat action (typing/looking).

        Args:
            action: Action to send. Defaults to ``ChatAction.TYPING``.

        Example::

            await message.answer_chat_action()
            await message.answer_chat_action(ChatAction.LOOKING)
        """
        from vkworkspace.enums.chat_action import ChatAction as ChatActionEnum

        return await self.bot.send_actions(
            self.chat.chat_id,
            str(action or ChatActionEnum.TYPING),
        )

    def typing(
        self,
        action: ChatAction | str | None = None,
        interval: float = 3.0,
    ) -> ChatActionSender:
        """Async context manager that sends "typing..." while the block runs.

        Args:
            action: Action to send. Defaults to ``ChatAction.TYPING``.
                Pass ``ChatAction.LOOKING`` for "looking" indicator.
            interval: Resend interval in seconds (default 3.0).

        Returns:
            ``ChatActionSender`` — use with ``async with``.

        Example::

            @router.message(Command("report"))
            async def report(message: Message):
                async with message.typing():
                    result = await slow_computation()
                await message.answer(result)
        """
        from vkworkspace.enums.chat_action import ChatAction as ChatActionEnum
        from vkworkspace.utils.actions import ChatActionSender

        return ChatActionSender(
            bot=self.bot,
            chat_id=self.chat.chat_id,
            action=action or ChatActionEnum.TYPING,
            interval=interval,
        )

    async def answer_file(
        self,
        file_id: str | None = None,
        file: Any = None,
        caption: str | None = None,
        parse_mode: ParseMode | str | None = _UNSET,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Message:
        """Send a file/image to the same chat.

        Returns a bound :class:`Message` — supports ``.delete()``.

        Args:
            file_id: ID of a previously uploaded file (no re-upload).
            file: ``InputFile`` or open ``BinaryIO`` to upload.
            caption: Text caption below the file.

        Example::

            await message.answer_file(file=InputFile("report.pdf"), caption="Here!")

        Note:
            VK Teams API returns only ``msgId`` on send. ``timestamp``,
            ``from_user``, and ``parts`` will be ``None`` / empty.
        """
        if parse_mode is not _UNSET:
            kwargs["parse_mode"] = parse_mode
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        resp = await self.bot.send_file(
            chat_id=self.chat.chat_id,
            file_id=file_id,
            file=file,
            caption=caption,
            **kwargs,
        )
        sent = Message.model_construct(msg_id=resp.msg_id or "", chat=self.chat, text=caption)
        sent.set_bot(self.bot)
        return sent

    async def answer_voice(
        self,
        file_id: str | None = None,
        file: Any = None,
        inline_keyboard_markup: Any = None,
        **kwargs: Any,
    ) -> Message:
        """Send a voice message to the same chat.

        Returns a bound :class:`Message` — supports ``.delete()``.

        Recommended format: OGG/Opus. Convert with
        ``vkworkspace.utils.voice.convert_to_ogg_opus()`` if needed.

        Args:
            file_id: ID of a previously uploaded voice.
            file: ``InputFile`` with OGG/Opus data.

        Example::

            ogg = convert_to_ogg_opus("audio.mp3")
            await message.answer_voice(file=InputFile(ogg, filename="voice.ogg"))

        Note:
            VK Teams API returns only ``msgId`` on send. ``timestamp``,
            ``from_user``, and ``parts`` will be ``None`` / empty.
        """
        if inline_keyboard_markup is not None:
            kwargs["inline_keyboard_markup"] = inline_keyboard_markup
        resp = await self.bot.send_voice(
            chat_id=self.chat.chat_id,
            file_id=file_id,
            file=file,
            **kwargs,
        )
        sent = Message.model_construct(msg_id=resp.msg_id or "", chat=self.chat)
        sent.set_bot(self.bot)
        return sent
