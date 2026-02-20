from __future__ import annotations

import re
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ValidationError

from .base import BaseFilter


class CallbackData(BaseFilter):
    """Filter callback queries by exact string or regex.

    Usage::

        @router.callback_query(CallbackData("confirm"))
        @router.callback_query(CallbackData(re.compile(r"^action_\\d+$")))
    """

    def __init__(self, data: str | re.Pattern[str]) -> None:
        self.data = data

    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        callback_data = getattr(event, "callback_data", None)
        if callback_data is None:
            return False

        if isinstance(self.data, re.Pattern):
            return bool(self.data.search(callback_data))
        return bool(callback_data == self.data)


# ── CallbackDataFactory ─────────────────────────────────────────────


class CallbackDataFactory(BaseModel):
    """Base class for structured, typed callback data.

    Eliminates manual string parsing — define fields once, pack/unpack
    automatically, filter with type safety.

    Define a subclass with ``prefix`` and typed fields::

        class ProductCB(CallbackDataFactory, prefix="product"):
            action: str
            id: int

    Create buttons::

        builder.button(
            text="Buy",
            callback_data=ProductCB(action="buy", id=42).pack(),
        )

    Filter and receive parsed data in handler::

        @router.callback_query(ProductCB.filter(F.action == "buy"))
        async def on_buy(query: CallbackQuery, callback_data: ProductCB):
            await query.answer(f"Buying product {callback_data.id}")

    The packed string format is ``prefix:value1:value2:...``,
    e.g. ``"product:buy:42"``.
    """

    __callback_prefix__: ClassVar[str]
    __callback_sep__: ClassVar[str] = ":"

    def __init_subclass__(
        cls,
        prefix: str = "",
        sep: str = ":",
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if not prefix:
            raise TypeError(
                f"{cls.__name__} must define a prefix: "
                f'class {cls.__name__}(CallbackDataFactory, prefix="...")'
            )
        cls.__callback_prefix__ = prefix
        cls.__callback_sep__ = sep

    def pack(self) -> str:
        """Serialize to a callback_data string.

        Returns:
            String like ``"prefix:val1:val2"`` ready for
            ``InlineKeyboardButton(callback_data=...)``.

        Example::

            cb = ProductCB(action="buy", id=42)
            cb.pack()  # "product:buy:42"
        """
        sep = self.__callback_sep__
        parts = [self.__callback_prefix__]
        parts.extend(str(getattr(self, name)) for name in type(self).model_fields)
        return sep.join(parts)

    @classmethod
    def unpack(cls, data: str) -> Self:
        """Parse a callback_data string back into this model.

        Args:
            data: Raw callback_data string, e.g. ``"product:buy:42"``.

        Raises:
            ValueError: If prefix doesn't match or wrong number of fields.

        Example::

            cb = ProductCB.unpack("product:buy:42")
            cb.action  # "buy"
            cb.id      # 42
        """
        sep = cls.__callback_sep__
        prefix = cls.__callback_prefix__
        parts = data.split(sep)

        if parts[0] != prefix:
            raise ValueError(f"Invalid prefix: expected {prefix!r}, got {parts[0]!r}")

        field_names = list(cls.model_fields.keys())
        values = parts[1:]

        if len(values) != len(field_names):
            raise ValueError(
                f"{cls.__name__}: expected {len(field_names)} values, got {len(values)}"
            )

        return cls(**dict(zip(field_names, values, strict=True)))

    @classmethod
    def filter(cls, rule: Any = None) -> _CallbackDataFilter:
        """Create a filter for this callback data type.

        Args:
            rule: Optional magic-filter rule to apply on the parsed object,
                e.g. ``F.action == "buy"``.

        Returns:
            A filter that matches the prefix, parses the data, and injects
            ``callback_data`` into the handler kwargs.

        Example::

            # Match any ProductCB callback
            @router.callback_query(ProductCB.filter())

            # Match only action == "buy"
            @router.callback_query(ProductCB.filter(F.action == "buy"))
        """
        return _CallbackDataFilter(cls, rule)

    def __str__(self) -> str:
        return self.pack()


class _CallbackDataFilter(BaseFilter):
    """Internal filter created by ``CallbackDataFactory.filter()``."""

    def __init__(
        self,
        factory: type[CallbackDataFactory],
        rule: Any = None,
    ) -> None:
        self._factory = factory
        self._rule = rule

    async def __call__(self, event: Any, **kwargs: Any) -> bool | dict[str, Any]:
        raw = getattr(event, "callback_data", None)
        if raw is None:
            return False

        # Quick prefix check before parsing
        prefix = self._factory.__callback_prefix__
        sep = self._factory.__callback_sep__
        if not raw.startswith(prefix + sep) and raw != prefix:
            return False

        try:
            parsed = self._factory.unpack(raw)
        except (ValueError, ValidationError):
            return False

        # Apply magic-filter rule if provided
        if self._rule is not None and hasattr(self._rule, "resolve"):
            try:
                if not self._rule.resolve(parsed):
                    return False
            except (AttributeError, KeyError, TypeError, ValueError):
                return False

        # Inject parsed callback_data into handler kwargs
        return {"callback_data": parsed}
