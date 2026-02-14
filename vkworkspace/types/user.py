from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import VKTeamsObject


class Photo(VKTeamsObject):
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class User(VKTeamsObject):
    user_id: str = Field(alias="userId")
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    nick: Optional[str] = None
    about: Optional[str] = None
    is_bot: Optional[bool] = Field(default=None, alias="isBot")


class Contact(VKTeamsObject):
    user_id: str = Field(alias="userId")
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    nick: Optional[str] = None


class ChatMember(User):
    creator: bool = False
    admin: bool = False


class BotInfo(VKTeamsObject):
    user_id: str = Field(alias="userId")
    nick: Optional[str] = None
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    about: Optional[str] = None
    photo: list[Photo] = Field(default_factory=list)
