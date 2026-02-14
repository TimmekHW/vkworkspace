"""
Middleware bot — demonstrates custom middleware for logging and access control.

Usage:
    python examples/middleware_bot.py
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from vkworkspace import BaseMiddleware, Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message

logging.basicConfig(level=logging.INFO)

router = Router()


# Custom middleware: log every message
class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        start = time.monotonic()
        result = await handler(event, data)
        elapsed = time.monotonic() - start
        logging.info("Handler took %.3f seconds", elapsed)
        return result


# Custom middleware: restrict access to certain users
class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: list[str]) -> None:
        self.admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        if from_user and from_user.user_id not in self.admin_ids:
            if hasattr(event, "answer"):
                await event.answer("Access denied. Admins only.")
            return None
        return await handler(event, data)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Hello! I'm a middleware demo bot.")


@router.message(F.text)
async def echo(message: Message) -> None:
    await message.answer(message.text)


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()

    # Register middleware on the router's message observer
    router.message.middleware.register(LoggingMiddleware())

    dp.include_router(router)

    print("Middleware bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
