from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import VKTeamsObject


class Button(VKTeamsObject):
    text: str
    url: Optional[str] = None
    callback_data: Optional[str] = Field(default=None, alias="callbackData")
    style: Optional[str] = None
