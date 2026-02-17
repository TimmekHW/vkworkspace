from __future__ import annotations

import re
from typing import Any

from .base import BaseFilter


class CallbackData(BaseFilter):
    """
    Filter callback queries by callback_data.

    Usage::

        @router.callback_query(CallbackData("confirm"))
        @router.callback_query(CallbackData(re.compile(r"^action_\\d+$")))
    """

    def __init__(self, data: str | re.Pattern[str]) -> None:
        self.data = data

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        callback_data = getattr(event, "callback_data", None)
        if callback_data is None:
            return False

        if isinstance(self.data, re.Pattern):
            return bool(self.data.search(callback_data))
        return bool(callback_data == self.data)
