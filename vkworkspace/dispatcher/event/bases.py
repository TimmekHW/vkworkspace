from __future__ import annotations

from typing import Final


class _Unhandled:
    def __repr__(self) -> str:
        return "UNHANDLED"

    def __bool__(self) -> bool:
        return False


UNHANDLED: Final = _Unhandled()


class SkipHandler(Exception):
    """Raise inside a handler to skip to the next matching handler."""


class CancelHandler(Exception):
    """Raise inside a handler to stop handler chain entirely."""
