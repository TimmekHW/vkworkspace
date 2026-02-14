from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class State:
    """
    Represents a single FSM state.

    Usage::

        class Form(StatesGroup):
            name = State()    # state string will be "Form:name"
            age = State()     # state string will be "Form:age"
    """

    def __init__(self, state: str | None = None) -> None:
        self._state_name: str | None = state
        self._group: type | None = None

    @property
    def state(self) -> str:
        group_name = self._group.__name__ if self._group else ""
        state_name = self._state_name or ""
        return f"{group_name}:{state_name}"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, State):
            return self.state == other.state
        if isinstance(other, str):
            return self.state == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.state)

    def __repr__(self) -> str:
        return f"<State '{self.state}'>"


class StatesGroupMeta(type):
    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> StatesGroupMeta:
        cls = super().__new__(mcs, name, bases, namespace)

        states: list[State] = []
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, State):
                attr_value._group = cls
                attr_value._state_name = attr_name
                states.append(attr_value)

        cls.__all_states__ = tuple(states)  # type: ignore[attr-defined]
        cls.__state_names__ = tuple(s.state for s in states)  # type: ignore[attr-defined]
        return cls

    def __contains__(cls, item: Any) -> bool:
        if isinstance(item, State):
            return item.state in cls.__state_names__  # type: ignore[attr-defined]
        if isinstance(item, str):
            return item in cls.__state_names__  # type: ignore[attr-defined]
        return False

    def __iter__(cls) -> Iterator[State]:
        return iter(cls.__all_states__)  # type: ignore[attr-defined]


class StatesGroup(metaclass=StatesGroupMeta):
    """
    Base class for defining state groups.

    Usage::

        class OrderForm(StatesGroup):
            waiting_product = State()
            waiting_quantity = State()
            confirm = State()
    """

    __all_states__: tuple[State, ...]
    __state_names__: tuple[str, ...]
