from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from vkworkspace.client.bot import Bot


class VKTeamsObject(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        extra="allow",
    )

    _bot: Bot | None = None

    def set_bot(self, bot: Bot) -> None:
        object.__setattr__(self, "_bot", bot)

    @property
    def bot(self) -> Bot:
        if self._bot is None:
            raise RuntimeError(
                "This object is not bound to a Bot instance. "
                "It was likely created manually, not from an API event."
            )
        return self._bot
