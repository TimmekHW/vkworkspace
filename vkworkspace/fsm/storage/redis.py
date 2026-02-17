from __future__ import annotations

import json
from typing import Any

from .base import BaseStorage, StorageKey


class RedisStorage(BaseStorage):
    """
    Redis-based FSM storage. Requires ``redis[hiredis]`` package.

    Usage::

        from redis.asyncio import Redis

        redis = Redis(host="localhost", port=6379, db=0)
        storage = RedisStorage(redis=redis)
        dp = Dispatcher(storage=storage)
    """

    def __init__(
        self,
        redis: Any,
        key_prefix: str = "vkworkspace",
        state_ttl: int | None = None,
        data_ttl: int | None = None,
    ) -> None:
        self._redis = redis
        self._key_prefix = key_prefix
        self._state_ttl = state_ttl
        self._data_ttl = data_ttl

    def _make_key(self, key: StorageKey, part: str) -> str:
        return f"{self._key_prefix}:fsm:{key.bot_id}:{key.chat_id}:{key.user_id}:{part}"

    async def set_state(self, key: StorageKey, state: str | None) -> None:
        redis_key = self._make_key(key, "state")
        if state is None:
            await self._redis.delete(redis_key)
        else:
            await self._redis.set(redis_key, state, ex=self._state_ttl)

    async def get_state(self, key: StorageKey) -> str | None:
        redis_key = self._make_key(key, "state")
        result = await self._redis.get(redis_key)
        if result is not None:
            return result.decode() if isinstance(result, bytes) else result
        return None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        redis_key = self._make_key(key, "data")
        if data:
            await self._redis.set(
                redis_key,
                json.dumps(data, ensure_ascii=False),
                ex=self._data_ttl,
            )
        else:
            await self._redis.delete(redis_key)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        redis_key = self._make_key(key, "data")
        result = await self._redis.get(redis_key)
        if result is not None:
            raw = result.decode() if isinstance(result, bytes) else result
            loaded: dict[str, Any] = json.loads(raw)
            return loaded
        return {}

    async def close(self) -> None:
        await self._redis.aclose()
