"""
Error handling bot — demonstrates @router.error(), lifecycle hooks,
and handle_edited_as_message.

Usage:
    python examples/features/error_handling.py
"""

import asyncio
import logging

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

router = Router(name="main")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Error handling demo:\n"
        "/crash — trigger an error (caught by @router.error)\n"
        "Edit any message — handled as new message\n"
    )


@router.message(Command("crash"))
async def cmd_crash(message: Message) -> None:
    await message.answer("About to crash...")
    raise ValueError("Intentional error for demo")


@router.message(F.text)
async def echo(message: Message) -> None:
    await message.answer(f"Echo: {message.text}")


# Error handler — catches exceptions from any handler in this router
@router.error()
async def on_error(event, error: Exception) -> None:
    logging.error("Handler raised %s: %s", type(error).__name__, error)
    if hasattr(event, "answer"):
        await event.answer(f"Something went wrong: {error}")


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )

    dp = Dispatcher(
        handle_edited_as_message=True,  # Edited messages go to @router.message
    )

    # Lifecycle hooks
    @dp.on_startup
    async def on_startup():
        me = await bot.get_me()
        logging.info("Bot '%s' started", me.nick if hasattr(me, "nick") else "?")

    @dp.on_shutdown
    async def on_shutdown():
        logging.info("Bot stopped, cleaning up...")

    dp.include_router(router)

    logging.info("Starting error handling bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
