from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import VKTeamsObject


class APIResponse(VKTeamsObject):
    ok: bool = True
    description: Optional[str] = None
    msg_id: Optional[str] = Field(default=None, alias="msgId")
    sn: Optional[str] = None
