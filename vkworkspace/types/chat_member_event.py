from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from .base import VKTeamsObject
from .chat import Chat
from .user import Contact

if TYPE_CHECKING:
    from vkworkspace.client.bot import Bot


class NewChatMembersEvent(VKTeamsObject):
    """Event fired when members join a chat (``newChatMembers``)."""

    chat: Chat = Field(default_factory=lambda: Chat(chatId="", type=""))
    new_members: list[Contact] = Field(default_factory=list, alias="newMembers")
    added_by: Contact | None = Field(default=None, alias="addedBy")

    async def is_bot_joined(self, bot: Bot) -> bool:
        """Check if the bot itself is among the new members."""
        me = await bot.get_me()
        return any(m.user_id == me.user_id for m in self.new_members)


class LeftChatMembersEvent(VKTeamsObject):
    """Event fired when members leave a chat (``leftChatMembers``)."""

    chat: Chat = Field(default_factory=lambda: Chat(chatId="", type=""))
    left_members: list[Contact] = Field(default_factory=list, alias="leftMembers")

    async def is_bot_left(self, bot: Bot) -> bool:
        """Check if the bot itself is among the members who left."""
        me = await bot.get_me()
        return any(m.user_id == me.user_id for m in self.left_members)


class ChangedChatInfoEvent(VKTeamsObject):
    """Event fired when chat info changes (``changedChatInfo``).

    Covers: title, about, rules, avatar, invite link, etc.
    Unknown fields are preserved via ``extra="allow"`` on VKTeamsObject.
    """

    chat: Chat = Field(default_factory=lambda: Chat(chatId="", type=""))
    changed_by: Contact | None = Field(default=None, alias="from")
    new_title: str | None = Field(default=None, alias="newTitle")
    new_about: str | None = Field(default=None, alias="newAbout")
    new_rules: str | None = Field(default=None, alias="newRules")
