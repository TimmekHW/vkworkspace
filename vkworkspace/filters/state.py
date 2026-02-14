from __future__ import annotations

from typing import Any

from ..fsm.state import State
from .base import BaseFilter


class StateFilter(BaseFilter):
    """
    Filter by FSM state.

    Usage::

        @router.message(StateFilter(MyStates.waiting_name))
        @router.message(StateFilter("*"))   # any state
        @router.message(StateFilter(None))  # no state (default)
    """

    def __init__(self, state: State | str | None) -> None:
        self.state = state

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        current_state = kwargs.get("current_state")

        if self.state == "*":
            return current_state is not None

        if self.state is None:
            return current_state is None

        if isinstance(self.state, State):
            return current_state == self.state.state

        return current_state == self.state
