from __future__ import annotations

import re
from typing import Any

from .base import BaseFilter


class RegexpFilter(BaseFilter):
    """
    Filter messages by regex pattern on text.

    Usage::

        @router.message(RegexpFilter(r"hello|hi|hey"))
        @router.message(RegexpFilter(re.compile(r"\\d{4}", re.IGNORECASE)))
    """

    def __init__(self, pattern: str | re.Pattern[str]) -> None:
        if isinstance(pattern, str):
            self.pattern = re.compile(pattern)
        else:
            self.pattern = pattern

    async def __call__(self, event: Any, **kwargs: Any) -> bool | dict[str, Any]:
        text = getattr(event, "text", None)
        if not text:
            return False

        match = self.pattern.search(text)
        if match:
            return {"regexp_match": match}
        return False
