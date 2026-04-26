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


class FileFilter(BaseFilter):
    """Match messages with a file attachment (any kind).

    Matches ``parts[].type == "file"``.  Use sub-classes :class:`ImageFilter`,
    :class:`AudioFilter`, :class:`VideoFilter` to filter by file kind.

    Usage::

        @router.message(FileFilter())
        async def on_file(message: Message) -> None:
            for part in message.parts:
                if file := part.as_file:
                    await message.answer(f"Got file: {file.file_id}")
    """

    _SUBTYPE: str | None = None

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        parts = getattr(event, "parts", [])
        for p in parts:
            if getattr(p, "type", "") != "file":
                continue
            if self._SUBTYPE is None:
                return True
            payload = getattr(p, "payload", None)
            sub = (payload or {}).get("type", "") if isinstance(payload, dict) else ""
            if sub == self._SUBTYPE:
                return True
        return False


class ImageFilter(FileFilter):
    """Match messages with an image attachment (file part with payload type ``"image"``)."""

    _SUBTYPE = "image"


class VideoFilter(FileFilter):
    """Match messages with a video attachment."""

    _SUBTYPE = "video"


class AudioFilter(FileFilter):
    """Match messages with an audio attachment."""

    _SUBTYPE = "audio"


class StickerFilter(BaseFilter):
    """Match messages containing a sticker (``parts[].type == "sticker"``)."""

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        parts = getattr(event, "parts", [])
        return any(getattr(p, "type", "") == "sticker" for p in parts)


class VoiceFilter(BaseFilter):
    """Match messages containing a voice message (``parts[].type == "voice"``)."""

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        parts = getattr(event, "parts", [])
        return any(getattr(p, "type", "") == "voice" for p in parts)


class MentionFilter(BaseFilter):
    """Match messages that contain at least one ``@mention`` part.

    If ``user_id`` is given, match only mentions of that user.

    Usage::

        @router.message(MentionFilter())             # any mention
        @router.message(MentionFilter("alice@corp")) # mention of specific user
    """

    def __init__(self, user_id: str | None = None) -> None:
        self.user_id = user_id

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        parts = getattr(event, "parts", [])
        for p in parts:
            if getattr(p, "type", "") != "mention":
                continue
            if self.user_id is None:
                return True
            payload = getattr(p, "payload", None)
            if isinstance(payload, dict) and payload.get("userId") == self.user_id:
                return True
        return False


class SenderFilter(BaseFilter):
    """Match events where ``from_user.user_id`` is one of the given user IDs.

    Usage::

        OWNER = "alice@corp"
        @router.message(SenderFilter(OWNER))
        async def admin_only(message: Message) -> None:
            ...

        @router.message(SenderFilter(["alice@corp", "bob@corp"]))
    """

    def __init__(self, user_id: str | list[str] | tuple[str, ...]) -> None:
        if isinstance(user_id, (list, tuple)):
            self.user_ids = frozenset(user_id)
        else:
            self.user_ids = frozenset({user_id})

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            return False
        uid = getattr(from_user, "user_id", None)
        return uid in self.user_ids


_URL_RE = re.compile(
    r"https?://[^\s<>\"'`]+|www\.[^\s<>\"'`]+",
    re.IGNORECASE,
)


class URLFilter(BaseFilter):
    """Match messages whose ``text`` contains an HTTP(S) URL."""

    async def __call__(self, event: Any, **kwargs: Any) -> bool | dict[str, Any]:
        text = getattr(event, "text", "") or ""
        if not text:
            return False
        match = _URL_RE.search(text[:_MAX_REGEX_TEXT])
        if match:
            return {"url": match.group(0)}
        return False


class CallbackDataRegexpFilter(BaseFilter):
    """Match callback queries whose ``callback_data`` matches a regular expression.

    Returns a dict with ``regexp_match`` (the :class:`re.Match` object) on success,
    so handlers can pull captured groups from kwargs.

    Usage::

        @router.callback_query(CallbackDataRegexpFilter(r"^order:(\\d+)$"))
        async def on_order(query: CallbackQuery, regexp_match) -> None:
            order_id = regexp_match.group(1)
    """

    def __init__(self, pattern: str | re.Pattern[str]) -> None:
        if isinstance(pattern, str):
            self.pattern = re.compile(pattern)
        else:
            self.pattern = pattern

    async def __call__(self, event: Any, **kwargs: Any) -> bool | dict[str, Any]:
        cb = getattr(event, "callback_data", None)
        if not cb:
            return False
        match = self.pattern.match(cb[:_MAX_REGEX_TEXT])
        if match:
            return {"regexp_match": match}
        return False


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
