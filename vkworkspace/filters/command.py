from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Union

from .base import BaseFilter


@dataclass
class CommandObject:
    """Parsed command result, injected into handler kwargs as ``command``."""

    prefix: str
    command: str
    args: str
    raw_text: str
    match: re.Match[str] | None = None


class Command(BaseFilter):
    """
    Filter for bot commands.

    Usage::

        @router.message(Command("start"))
        @router.message(Command("help", "info"))
        @router.message(Command(re.compile(r"cmd_\\d+")))
        @router.message(Command("start", prefix="/"))
        @router.message(Command("menu", prefix=("/", "!", "#", "")))
    """

    def __init__(
        self,
        *commands: Union[str, re.Pattern[str]],
        prefix: str | tuple[str, ...] = "/",
        ignore_case: bool = True,
    ) -> None:
        self.commands = commands
        self.prefixes: tuple[str, ...] = (
            prefix if isinstance(prefix, tuple) else (prefix,)
        )
        self.ignore_case = ignore_case

    async def __call__(
        self, event: Any, **kwargs: Any
    ) -> bool | dict[str, Any]:
        text = getattr(event, "text", None)
        if not text:
            return False

        text = text.strip()

        # Try each prefix (longest first to avoid empty prefix matching everything)
        matched_prefix: str | None = None
        for pfx in sorted(self.prefixes, key=len, reverse=True):
            if text.startswith(pfx):
                matched_prefix = pfx
                break

        if matched_prefix is None:
            return False

        without_prefix = text[len(matched_prefix):]
        parts = without_prefix.split(maxsplit=1)
        command_text = parts[0] if parts else ""
        args_text = parts[1] if len(parts) > 1 else ""

        if not command_text:
            return False

        cmd_obj = CommandObject(
            prefix=matched_prefix,
            command=command_text,
            args=args_text,
            raw_text=text,
        )

        # Match any command if none specified
        if not self.commands:
            return {"command": cmd_obj}

        for cmd in self.commands:
            if isinstance(cmd, re.Pattern):
                match = cmd.match(command_text)
                if match:
                    cmd_obj.match = match
                    return {"command": cmd_obj}
            else:
                target = cmd.lower() if self.ignore_case else cmd
                actual = command_text.lower() if self.ignore_case else command_text
                if target == actual:
                    return {"command": cmd_obj}

        return False
