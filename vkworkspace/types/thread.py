from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import VKTeamsObject


class Thread(VKTeamsObject):
    thread_id: str = Field(alias="threadId")
    msg_id: Optional[str] = Field(default=None, alias="msgId")


class Subscriber(VKTeamsObject):
    user_id: str = Field(alias="userId")
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    nick: Optional[str] = None


class ThreadSubscribers(VKTeamsObject):
    cursor: Optional[str] = None
    subscribers: list[Subscriber] = Field(default_factory=list)
