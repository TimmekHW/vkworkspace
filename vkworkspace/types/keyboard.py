from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class Button(VKTeamsObject):
    text: str
    url: str | None = None
    callback_data: str | None = Field(default=None, alias="callbackData")
    style: str | None = None
