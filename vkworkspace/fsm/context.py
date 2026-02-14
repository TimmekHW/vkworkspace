from __future__ import annotations

from typing import Any

from .state import State
from .storage.base import BaseStorage, StorageKey


class FSMContext:
    """
    User-facing FSM context. Injected into handlers as ``state``.

    Usage::

        @router.message(StateFilter(Form.name))
        async def process_name(message: Message, state: FSMContext):
            await state.update_data(name=message.text)
            await state.set_state(Form.age)
            await message.answer("Now enter your age:")
    """

    def __init__(self, storage: BaseStorage, key: StorageKey) -> None:
        self._storage = storage
        self._key = key

    async def set_state(self, state: State | str | None = None) -> None:
        state_str = state.state if isinstance(state, State) else state
        await self._storage.set_state(key=self._key, state=state_str)

    async def get_state(self) -> str | None:
        return await self._storage.get_state(key=self._key)

    async def set_data(self, data: dict[str, Any]) -> None:
        await self._storage.set_data(key=self._key, data=data)

    async def get_data(self) -> dict[str, Any]:
        return await self._storage.get_data(key=self._key)

    async def update_data(self, **kwargs: Any) -> dict[str, Any]:
        data = await self.get_data()
        data.update(kwargs)
        await self.set_data(data)
        return data

    async def clear(self) -> None:
        await self.set_state(None)
        await self.set_data({})
