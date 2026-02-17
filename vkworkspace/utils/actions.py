"""Chat action helpers (typing, looking).

Provides two ways to show a chat action indicator:

1. **Decorator** — wraps a handler, sends action while it runs::

    from vkworkspace.utils.actions import typing_action

    @router.message(Command("report"))
    @typing_action
    async def generate_report(message: Message):
        result = await slow_computation()   # user sees "Bot is typing..."
        await message.answer(result)

2. **Async context manager** — explicit control::

    async with ChatActionSender(bot=bot, chat_id=chat_id):
        result = await slow_computation()

    # Or via Message shortcut:
    async with message.typing():
        result = await slow_computation()
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from vkworkspace.enums.chat_action import ChatAction

if TYPE_CHECKING:
    from vkworkspace.client.bot import Bot


def typing_action(
    func: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    *,
    action: str | ChatAction = ChatAction.TYPING,
    interval: float = 3.0,
) -> Any:
    """Show a chat action while the handler is running.

    Can be used as a simple decorator or with parameters::

        @typing_action
        async def handler(message): ...

        @typing_action(action=ChatAction.LOOKING)
        async def handler(message): ...

        @typing_action(interval=5.0)
        async def handler(message): ...

    Args:
        func: The handler function (auto-filled when used without parentheses).
        action: Action to send — ``ChatAction.TYPING`` (default) or
            ``ChatAction.LOOKING``.
        interval: How often to resend the action in seconds (default 3).
            VK Teams typing indicator expires after ~5s.
    """

    def decorator(
        fn: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        @functools.wraps(fn)
        async def wrapper(event: Any, **kwargs: Any) -> Any:
            chat = getattr(event, "chat", None)
            chat_id = getattr(chat, "chat_id", None) if chat else None
            bot = getattr(event, "bot", None)

            if not chat_id or not bot:
                return await fn(event, **kwargs)

            async def _keep_sending() -> None:
                while True:
                    await bot.send_actions(chat_id, str(action))
                    await asyncio.sleep(interval)

            task = asyncio.create_task(_keep_sending())
            try:
                return await fn(event, **kwargs)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


class ChatActionSender:
    """Async context manager that sends a chat action periodically.

    Sends the action immediately on enter and repeats every *interval*
    seconds until the ``async with`` block exits.

    Args:
        bot: Bot instance.
        chat_id: Target chat ID.
        action: Action to send (default ``ChatAction.TYPING``).
        interval: Resend interval in seconds (default 3.0).
            VK Teams indicator expires after ~5 s.

    Example::

        async with ChatActionSender(bot=bot, chat_id=chat_id):
            result = await slow_computation()

        # With custom action:
        async with ChatActionSender(
            bot=bot, chat_id=chat_id, action=ChatAction.LOOKING,
        ):
            ...

    Typically used via ``Message.typing()`` shortcut::

        async with message.typing():
            result = await slow_computation()
    """

    def __init__(
        self,
        bot: Bot,
        chat_id: str,
        *,
        action: str | ChatAction = ChatAction.TYPING,
        interval: float = 3.0,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.action = str(action)
        self.interval = interval
        self._task: asyncio.Task[None] | None = None

    async def _keep_sending(self) -> None:
        while True:
            await self.bot.send_actions(self.chat_id, self.action)
            await asyncio.sleep(self.interval)

    async def __aenter__(self) -> ChatActionSender:
        self._task = asyncio.create_task(self._keep_sending())
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # ── Convenience constructors ──────────────────────────────────

    @classmethod
    def typing(
        cls,
        bot: Bot,
        chat_id: str,
        interval: float = 3.0,
    ) -> ChatActionSender:
        """Shortcut for ``ChatActionSender(..., action=ChatAction.TYPING)``."""
        return cls(bot=bot, chat_id=chat_id, action=ChatAction.TYPING, interval=interval)

    @classmethod
    def looking(
        cls,
        bot: Bot,
        chat_id: str,
        interval: float = 3.0,
    ) -> ChatActionSender:
        """Shortcut for ``ChatActionSender(..., action=ChatAction.LOOKING)``."""
        return cls(bot=bot, chat_id=chat_id, action=ChatAction.LOOKING, interval=interval)
