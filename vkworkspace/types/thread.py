from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class Thread(VKTeamsObject):
    thread_id: str = Field(alias="threadId")
    msg_id: str | None = Field(default=None, alias="msgId")


class Subscriber(VKTeamsObject):
    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None


class ThreadSubscribers(VKTeamsObject):
    cursor: str | None = None
    subscribers: list[Subscriber] = Field(default_factory=list)
