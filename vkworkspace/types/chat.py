from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class Chat(VKTeamsObject):
    chat_id: str = Field(alias="chatId")
    type: str = ""
    title: str | None = None


class ChatInfo(VKTeamsObject):
    type: str = ""
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None
    about: str | None = None
    rules: str | None = None
    title: str | None = None
    is_bot: bool | None = Field(default=None, alias="isBot")
    public: bool | None = None
    join_moderation: bool | None = Field(default=None, alias="joinModeration")
    invite_link: str | None = Field(default=None, alias="inviteLink")
    language: str | None = None
