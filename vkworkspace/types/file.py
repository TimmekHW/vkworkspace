from __future__ import annotations

from pydantic import Field

from .base import VKTeamsObject


class File(VKTeamsObject):
    """File info. Returned by ``bot.get_file_info()``."""

    file_id: str | None = Field(default=None, alias="fileId")
    type: str | None = None
    size: int | None = None
    filename: str | None = None
    url: str | None = None
