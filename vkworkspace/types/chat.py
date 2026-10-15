from __future__ import annotations

from pydantic import AliasChoices, Field

from .base import VKTeamsObject
from .user import Photo, _NamedUser


class Chat(VKTeamsObject):
    """Chat reference (available as ``message.chat``).

    Attributes:
        chat_id: Chat ID (email-like for DMs, hash for groups).
        type: ``"private"``, ``"group"``, or ``"channel"``.
        title: Group/channel title (``None`` for private chats).
    """

    chat_id: str = Field(alias="chatId")
    type: str = ""
    title: str | None = None


class ChatInfo(_NamedUser, VKTeamsObject):
    """Full chat information. Returned by ``bot.get_chat_info()``.

    For a private chat (a user) ``first_name`` / ``last_name`` / ``nick`` are
    filled and ``full_name`` works; for groups use ``title``.
    """

    type: str = ""
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None
    about: str | None = None
    rules: str | None = None
    title: str | None = None
    is_bot: bool | None = Field(default=None, alias="isBot")
    phone: str | None = None
    # The API sends ``photo``; ``photos`` kept for backward compatibility.
    photos: list[Photo] = Field(
        default_factory=list,
        validation_alias=AliasChoices("photo", "photos"),
    )
    public: bool | None = None
    join_moderation: bool | None = Field(default=None, alias="joinModeration")
    invite_link: str | None = Field(default=None, alias="inviteLink")
    language: str | None = None
