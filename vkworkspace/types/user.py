from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class Photo(VKTeamsObject):
    """User/chat avatar photo."""

    url: str
    width: int | None = None
    height: int | None = None


class User(VKTeamsObject):
    """VK Teams user profile.

    Attributes:
        user_id: Email-like ID (e.g. ``"user@company.ru"``).
        first_name: First name.
        last_name: Last name.
        nick: Display nickname.
        about: Bio / status text.
        is_bot: ``True`` if this user is a bot.
    """

    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None
    about: str | None = None
    is_bot: bool | None = Field(default=None, alias="isBot")


class Contact(VKTeamsObject):
    """Lightweight user info (``message.from_user``)."""

    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None


class ChatMember(User):
    """Chat member with admin/creator flags."""

    creator: bool = False
    admin: bool = False


class BotInfo(VKTeamsObject):
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
