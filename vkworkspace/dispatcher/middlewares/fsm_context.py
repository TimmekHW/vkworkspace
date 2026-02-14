from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ...fsm.context import FSMContext
from ...fsm.storage.base import BaseStorage, StorageKey
from ...fsm.strategy import FSMStrategy
from .base import BaseMiddleware


class FSMContextMiddleware(BaseMiddleware):
    def __init__(
        self,
        storage: BaseStorage,
        strategy: FSMStrategy = FSMStrategy.USER_IN_CHAT,
    ) -> None:
        self.storage = storage
        self.strategy = strategy

    def _build_key(self, event: Any, data: dict[str, Any]) -> StorageKey | None:
        bot = data.get("bot")
        chat = getattr(event, "chat", None)
        from_user = getattr(event, "from_user", None)

        chat_id = getattr(chat, "chat_id", None) if chat else None
        user_id = getattr(from_user, "user_id", None) if from_user else None

        if not chat_id and not user_id:
            return None

        bot_id = bot.token[:16] if bot else "unknown"

        if self.strategy == FSMStrategy.USER_IN_CHAT:
            return StorageKey(bot_id=bot_id, chat_id=chat_id or "", user_id=user_id or "")
        if self.strategy == FSMStrategy.CHAT:
            return StorageKey(bot_id=bot_id, chat_id=chat_id or "", user_id="")
        if self.strategy == FSMStrategy.GLOBAL_USER:
            return StorageKey(bot_id=bot_id, chat_id="", user_id=user_id or "")

        return None

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        key = self._build_key(event, data)

        if key is not None:
            fsm_context = FSMContext(storage=self.storage, key=key)
            current_state = await fsm_context.get_state()
            data["state"] = fsm_context
            data["current_state"] = current_state
        else:
            data["state"] = None
            data["current_state"] = None

        return await handler(event, data)
