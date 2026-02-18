"""
Custom prefix bot — demonstrates Command filter with custom prefixes
and command argument parsing.

Usage:
    python examples/features/custom_prefix.py
"""

import asyncio
import re

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.filters.command import CommandObject
from vkworkspace.types import Message

router = Router()


# Standard /start command
@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Custom prefix demo:\n"
        "/help or !help — show help\n"
        "/ban user@co — ban a user\n"
        "!ping — pong\n"
        "Any text starting with 'calc' — regex command"
    )


# Multiple prefixes: responds to /help AND !help
@router.message(Command("help", prefix=("/", "!")))
async def cmd_help(message: Message, command: CommandObject) -> None:
    await message.answer(
        f"Help requested with prefix '{command.prefix}'\n"
        f"Full text: {command.raw_text}"
    )


# Command with arguments
@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Usage: /ban user@company.ru [reason]")
        return
    await message.answer(f"Banned: {command.args}")


# ! prefix only
@router.message(Command("ping", prefix="!"))
async def cmd_ping(message: Message) -> None:
    await message.answer("pong!")


# Regex command: matches /calc_add, /calc_sub, /calc_mul, etc.
@router.message(Command(re.compile(r"calc_(\w+)")))
async def cmd_calc(message: Message, command: CommandObject) -> None:
    operation = command.match.group(1) if command.match else "?"
    await message.answer(f"Calculator: operation = {operation}, args = {command.args}")


# No prefix — responds to plain "status" text at the start
@router.message(Command("status", prefix=""))
async def cmd_status(message: Message) -> None:
    await message.answer("All systems operational")


@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Unknown command. Try /start")


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("Custom prefix bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
