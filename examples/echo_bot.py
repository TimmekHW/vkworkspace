"""
Simple echo bot — replies with the same text it receives.

Usage:
    python examples/echo_bot.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Hello! I'm an echo bot.\n"
        "Send me any text and I'll repeat it back."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message"
    )


@router.message(Command("vanish"))
async def cmd_vanish(message: Message) -> None:
    sent = await message.answer("I will vanish in 5 seconds...")
    await asyncio.sleep(5)
    await sent.delete()


@router.message(F.text)
async def echo(message: Message) -> None:
    assert message.text is not None  # guaranteed by F.text filter
    await message.answer(message.text)


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
