from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import VKTeamsObject


class Chat(VKTeamsObject):
    chat_id: str = Field(alias="chatId")
    type: str = ""
    title: Optional[str] = None


class ChatInfo(VKTeamsObject):
    type: str = ""
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    nick: Optional[str] = None
    about: Optional[str] = None
    rules: Optional[str] = None
    title: Optional[str] = None
    is_bot: Optional[bool] = Field(default=None, alias="isBot")
    public: Optional[bool] = None
    join_moderation: Optional[bool] = Field(default=None, alias="joinModeration")
    invite_link: Optional[str] = Field(default=None, alias="inviteLink")
    language: Optional[str] = None
