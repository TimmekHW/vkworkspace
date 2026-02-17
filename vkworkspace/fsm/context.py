from __future__ import annotations

from typing import Any

from .state import State
from .storage.base import BaseStorage, StorageKey


class FSMContext:
    """User-facing FSM context. Auto-injected as ``state`` kwarg in handlers.

    Manages the current state and arbitrary key-value data for a user/chat
    pair. Use it to build multi-step dialogs (registration forms, wizards, etc.).

    Example::

        class Form(StatesGroup):
            name = State()
            age = State()

        @router.message(Command("register"))
        async def start(message: Message, state: FSMContext):
            await state.set_state(Form.name)
            await message.answer("What is your name?")

        @router.message(StateFilter(Form.name), F.text)
        async def got_name(message: Message, state: FSMContext):
            await state.update_data(name=message.text)
            await state.set_state(Form.age)
            await message.answer("How old are you?")

        @router.message(StateFilter(Form.age), F.text)
        async def got_age(message: Message, state: FSMContext):
            data = await state.get_data()  # {"name": "John"}
            await state.clear()
            await message.answer(f"Done! {data['name']}, age {message.text}")
    """

    def __init__(self, storage: BaseStorage, key: StorageKey) -> None:
        self._storage = storage
        self._key = key

    async def set_state(self, state: State | str | None = None) -> None:
        """Set the current FSM state.

        Args:
            state: A ``State`` instance, state string, or ``None`` to clear.
        """
        state_str = state.state if isinstance(state, State) else state
        await self._storage.set_state(key=self._key, state=state_str)

    async def get_state(self) -> str | None:
        """Get the current FSM state string, or ``None`` if not set."""
        return await self._storage.get_state(key=self._key)

    async def set_data(self, data: dict[str, Any]) -> None:
        """Replace all FSM data with *data*."""
        await self._storage.set_data(key=self._key, data=data)

    async def get_data(self) -> dict[str, Any]:
        """Get all stored FSM data as a dict."""
        return await self._storage.get_data(key=self._key)

    async def update_data(self, **kwargs: Any) -> dict[str, Any]:
        """Merge *kwargs* into existing data and return the result.

        Example::

            await state.update_data(name="John", age=25)
            data = await state.get_data()  # {"name": "John", "age": 25}
        """
        data = await self.get_data()
        data.update(kwargs)
        await self.set_data(data)
        return data

    async def clear(self) -> None:
        """Clear both state and data. Ends the FSM dialog."""
        await self.set_state(None)
        await self.set_data({})
