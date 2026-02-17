from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import VKTeamsObject


class Update(VKTeamsObject):
    """Raw event from ``events/get``. Resolved into typed objects by the Dispatcher."""

    event_id: int = Field(alias="eventId")
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
