from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


DEFAULT_DESTINY = "default"


@dataclass(frozen=True)
class StorageKey:
    bot_id: str
    chat_id: str
    user_id: str
    destiny: str = DEFAULT_DESTINY


class BaseStorage(ABC):
    @abstractmethod
    async def set_state(self, key: StorageKey, state: str | None) -> None: ...

    @abstractmethod
    async def get_state(self, key: StorageKey) -> str | None: ...

    @abstractmethod
    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_data(self, key: StorageKey) -> dict[str, Any]: ...

    @abstractmethod
    async def close(self) -> None: ...
