from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import VKTeamsObject


class File(VKTeamsObject):
    file_id: Optional[str] = Field(default=None, alias="fileId")
    type: Optional[str] = None
    size: Optional[int] = None
    filename: Optional[str] = None
    url: Optional[str] = None
