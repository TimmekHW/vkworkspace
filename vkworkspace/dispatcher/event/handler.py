from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

logger = logging.getLogger(__name__)


@dataclass
class FilterObject:
    callback: Any

    async def check(self, event: Any, kwargs: dict[str, Any]) -> bool | dict[str, Any]:
        cb = self.callback

        # magic-filter (has .resolve method)
        if hasattr(cb, "resolve"):
            try:
                result = cb.resolve(event)
                return bool(result)
            except (AttributeError, KeyError, TypeError, ValueError):
                return False

        # BaseFilter or async callable
        if callable(cb):
            if inspect.iscoroutinefunction(cb.__call__) or inspect.iscoroutinefunction(cb):
                result = cb(event, **kwargs)
                return cast(bool | dict[str, Any], await result)  # type: ignore[reportGeneralTypeIssues]
            return cast(bool | dict[str, Any], cb(event, **kwargs))

        return bool(cb)


@dataclass
class HandlerObject:
    callback: Callable[..., Awaitable[Any]]
    filters: list[FilterObject] | None = None
    flags: dict[str, Any] = field(default_factory=dict)

    _params: set[str] = field(default_factory=set, init=False, repr=False)
    _has_kwargs: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        sig = inspect.signature(self.callback)
        self._params = set()
        self._has_kwargs = False
        for name, param in sig.parameters.items():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                self._has_kwargs = True
            else:
                self._params.add(name)

    async def check(
        self, event: Any, kwargs: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        if not self.filters:
            return True, kwargs

        for f in self.filters:
            result = await f.check(event, kwargs)
            if result is False:
                return False, kwargs
            if isinstance(result, dict):
                kwargs.update(result)
            elif result is not True and result is not None and not result:
                return False, kwargs

        return True, kwargs

    async def call(self, event: Any, **kwargs: Any) -> Any:
        if self._has_kwargs:
            return await self.callback(event, **kwargs)
        filtered = {k: v for k, v in kwargs.items() if k in self._params}
        return await self.callback(event, **filtered)
