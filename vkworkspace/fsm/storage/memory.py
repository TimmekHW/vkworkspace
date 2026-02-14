from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .base import BaseStorage, StorageKey


@dataclass
class _StorageRecord:
    state: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class MemoryStorage(BaseStorage):
    """
    In-memory FSM storage. Data is lost on restart.
    Suitable for development and testing.
    """

    def __init__(self) -> None:
        self._storage: dict[StorageKey, _StorageRecord] = defaultdict(_StorageRecord)

    async def set_state(self, key: StorageKey, state: str | None) -> None:
        self._storage[key].state = state

    async def get_state(self, key: StorageKey) -> str | None:
        return self._storage[key].state

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        self._storage[key].data = data.copy()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return self._storage[key].data.copy()

    async def close(self) -> None:
        self._storage.clear()
