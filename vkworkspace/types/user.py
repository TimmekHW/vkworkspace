from __future__ import annotations

import re

from pydantic import Field

from .base import VKTeamsObject

_UIN_RE = re.compile(r"targetSn=(\d+)")


class _NamedUser:
    """Name / mention helpers shared by every user-like object.

    Works on anything with ``first_name`` / ``last_name`` / ``nick`` /
    ``user_id`` attributes (``User``, ``Contact``, ``MentionPayload``, …).
    """

    @property
    def full_name(self) -> str:
        """``"Имя Фамилия"``; falls back to ``nick``, then ``user_id``.

        Example::

            message.from_user.full_name   # "Иван Иванов"
            message.mentions[0].full_name # "Пётр Петров"
        """
        parts = [
            p.strip()
            for p in (getattr(self, "first_name", None), getattr(self, "last_name", None))
            if p and p.strip()
        ]
        if parts:
            return " ".join(parts)
        return getattr(self, "nick", None) or getattr(self, "user_id", None) or ""

    @property
    def mention(self) -> str:
        """Mention markup ``@[user_id]`` for plain / HTML text.

        Example::

            await message.answer(f"{message.from_user.mention}, привет!")
        """
        user_id = getattr(self, "user_id", None)
        return f"@[{user_id}]" if user_id else ""

    @property
    def mention_md(self) -> str:
        """Mention markup for ``parse_mode="MarkdownV2"`` (escaped)."""
        user_id = getattr(self, "user_id", None)
        if not user_id:
            return ""
        from vkworkspace.utils.text import md

        return md.mention(user_id)


class Photo(VKTeamsObject):
    """User/chat avatar photo."""

    url: str
    width: int | None = None
    height: int | None = None


class User(_NamedUser, VKTeamsObject):
    """VK Teams user profile.

    Attributes:
        user_id: Email-like ID (e.g. ``"user@company.ru"``).
        first_name: First name.
        last_name: Last name.
        nick: Display nickname.
        about: Bio / status text.
        is_bot: ``True`` if this user is a bot.

    Properties: ``full_name``, ``mention``, ``mention_md``.
    """

    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None
    about: str | None = None
    is_bot: bool | None = Field(default=None, alias="isBot")


class UserInfo(User):
    """User profile resolved by :meth:`Bot.get_user` (``chats/getInfo``).

    Attributes:
        uin: Numeric ID parsed from the avatar URL (``targetSn=…``). This is
            the ID VK Teams uses for bots; for people ``user_id`` is the email.
        photos: Avatar photos.

    Example::

        user = await bot.get_user("ivanov@company.ru")
        user.full_name   # "Иван Иванов"
        user.mention     # "@[ivanov@company.ru]"
    """

    uin: str | None = None
    photos: list[Photo] = Field(default_factory=list)

    @staticmethod
    def parse_uin(photos: list[Photo]) -> str | None:
        """Extract the numeric ``targetSn`` ID from avatar URLs, if present."""
        for photo in photos:
            if m := _UIN_RE.search(photo.url or ""):
                return m.group(1)
        return None


class Contact(_NamedUser, VKTeamsObject):
    """Lightweight user info (``message.from_user``).

    Properties: ``full_name``, ``mention``, ``mention_md``.
    """

    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None


class ChatMember(User):
    """Chat member with admin/creator flags."""

    creator: bool = False
    admin: bool = False


class BotInfo(_NamedUser, VKTeamsObject):
    """Bot's own profile. Returned by ``bot.get_me()``.

    Example::

        me = await bot.get_me()
        print(me.nick, me.user_id)
    """

    user_id: str = Field(alias="userId")
    nick: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    about: str | None = None
    photo: list[Photo] = Field(default_factory=list)
