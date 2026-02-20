from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class Thread(VKTeamsObject):
    """Result of ``threads/add``.

    ``thread_id`` is the chat ID of the newly created thread
    (format: ``XXXXXXXXX@chat.agent``).  Thread messages arrive as
    ``newMessage`` events with ``chat.chatId == thread_id`` and
    ``parent_topic.chatId`` pointing back to the original chat.
    """

    thread_id: str = Field(default="", alias="threadId")
    msg_id: str | None = Field(default=None, alias="msgId")
    ok: bool = Field(default=False)


class Subscriber(VKTeamsObject):
    user_id: str = Field(alias="userId")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    nick: str | None = None


class ThreadSubscribers(VKTeamsObject):
    cursor: str | None = None
    subscribers: list[Subscriber] = Field(default_factory=list)
