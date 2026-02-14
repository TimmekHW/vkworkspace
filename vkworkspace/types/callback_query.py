from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .base import VKTeamsObject
from .chat import Chat
from .message import Message
from .user import Contact


class CallbackQuery(VKTeamsObject):
    query_id: str = Field(alias="queryId")
    chat: Chat | None = None
    from_user: Contact | None = Field(default=None, alias="from")
    message: Message | None = None
    callback_data: str = Field(default="", alias="callbackData")

    @model_validator(mode="after")
    def _extract_chat_from_message(self) -> CallbackQuery:
        """VK Teams API puts chat inside message, not at top level."""
        if self.chat is None and self.message is not None:
            self.chat = self.message.chat
        if self.from_user is None and self.message is not None:
            self.from_user = self.message.from_user
        return self

    async def answer(
        self,
        text: str = "",
        show_alert: bool = False,
        url: str | None = None,
    ) -> Any:
        return await self.bot.answer_callback_query(
            query_id=self.query_id,
            text=text,
            show_alert=show_alert,
            url=url,
        )
