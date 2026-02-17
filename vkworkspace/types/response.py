from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class APIResponse(VKTeamsObject):
    """Response from VK Teams API methods (``send_text``, ``send_file``, etc.)."""

    ok: bool = True
    description: str | None = None
    msg_id: str | None = Field(default=None, alias="msgId")
    sn: str | None = None
