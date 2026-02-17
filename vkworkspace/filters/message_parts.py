from __future__ import annotations

import re
from typing import Any

from .base import BaseFilter

_MAX_REGEX_TEXT = 8192  # guard against ReDoS on very long input


class ReplyFilter(BaseFilter):
    """Match messages that are replies to another message.

    Usage::

        @router.message(ReplyFilter())
        async def on_reply(message: Message) -> None:
            original = message.reply_to
            await message.answer(f"You replied to: {original.text}")
    """

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        parts = getattr(event, "parts", [])
        return any(getattr(p, "type", "") == "reply" for p in parts)


class ForwardFilter(BaseFilter):
    """Match messages that contain forwarded messages.

    Usage::

        @router.message(ForwardFilter())
        async def on_forward(message: Message) -> None:
            for fwd in message.forwards:
                await message.answer(f"Forwarded: {fwd.text}")
    """

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        parts = getattr(event, "parts", [])
        return any(getattr(p, "type", "") == "forward" for p in parts)


class RegexpPartsFilter(BaseFilter):
    """Match messages where text inside reply/forward parts matches a regex.

    Inspects the ``text`` field of inner messages in ``reply`` and ``forward``
    parts.  Useful for reacting based on the content of quoted/forwarded text.

    Usage::

        @router.message(RegexpPartsFilter(r"urgent|asap"))
        async def on_urgent_forward(message: Message) -> None:
            await message.answer("Forwarded/replied message contains urgent text!")
    """

    def __init__(self, pattern: str | re.Pattern[str]) -> None:
        if isinstance(pattern, str):
            self.pattern = re.compile(pattern)
        else:
            self.pattern = pattern

    async def __call__(self, event: Any, **kwargs: Any) -> bool | dict[str, Any]:
        parts = getattr(event, "parts", [])
        for part in parts:
            ptype = getattr(part, "type", "")
            if ptype not in ("reply", "forward"):
                continue
            payload = getattr(part, "payload", None)
            if not isinstance(payload, dict):
                continue
            message = payload.get("message", {})
            text = message.get("text") if isinstance(message, dict) else None
            if text:
                match = self.pattern.search(text[:_MAX_REGEX_TEXT])
                if match:
                    return {"regexp_parts_match": match}
        return False
