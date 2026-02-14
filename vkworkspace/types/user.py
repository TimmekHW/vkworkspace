from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class Photo(VKTeamsObject):
    url: str
    width: int | None = None
    height: int | None = None


class User(VKTeamsObject):
    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None
    about: str | None = None
    is_bot: bool | None = Field(default=None, alias="isBot")


class Contact(VKTeamsObject):
    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None


class ChatMember(User):
    creator: bool = False
    admin: bool = False


class BotInfo(VKTeamsObject):
    user_id: str = Field(alias="userId")
    nick: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    about: str | None = None
    photo: list[Photo] = Field(default_factory=list)
