from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class APIResponse(VKTeamsObject):
    ok: bool = True
    description: str | None = None
    msg_id: str | None = Field(default=None, alias="msgId")
    sn: str | None = None
