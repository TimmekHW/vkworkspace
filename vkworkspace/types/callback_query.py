from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .base import VKTeamsObject
from .chat import Chat
from .message import Message
from .user import Contact


class CallbackQuery(VKTeamsObject):
    """Incoming callback from an inline keyboard button press.

    Received in ``@router.callback_query()`` handlers.

    Attributes:
        query_id: Unique query ID (used internally by ``.answer()``).
        chat: Chat where the button was pressed.
        from_user: User who pressed the button.
        message: Original message that contained the keyboard.
        callback_data: Data string from the pressed button.

    Example::

        @router.callback_query(F.callback_data == "confirm")
        async def on_confirm(query: CallbackQuery):
            await query.answer("Done!")
            # Edit the original message
            if query.message:
                await query.message.edit_text("Confirmed!")
    """

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
        """Respond to the callback query.

        Must be called within ~30 seconds, otherwise the user sees a
        loading spinner on the button.

        Args:
            text: Notification text (toast or alert).
            show_alert: ``True`` = popup alert, ``False`` = small toast.
            url: URL to open in the user's browser.
        """
        return await self.bot.answer_callback_query(
            query_id=self.query_id,
            text=text,
            show_alert=show_alert,
            url=url,
        )
