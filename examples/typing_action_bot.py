"""
Typing action bot — shows "Bot is typing..." while processing.

Demonstrates three ways to send chat actions:
  /slow      — @typing_action decorator (auto typing while handler runs)
  /report    — async with message.typing() context manager
  /ping      — await message.answer_chat_action() one-shot

Usage:
    python examples/typing_action_bot.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, Router
from vkworkspace.enums import ChatAction
from vkworkspace.filters import Command
from vkworkspace.types import Message
from vkworkspace.utils.actions import typing_action

router = Router()


# ── 1. Decorator — simplest way ──────────────────────────────────


@router.message(Command("slow"))
@typing_action
async def cmd_slow(message: Message) -> None:
    """User sees "typing..." for 3 seconds, then gets the result."""
    await asyncio.sleep(3)
    await message.answer("Done! (decorator)")


@router.message(Command("look"))
@typing_action(action=ChatAction.LOOKING)
async def cmd_look(message: Message) -> None:
    await asyncio.sleep(2)
    await message.answer("Done looking! (decorator)")


# ── 2. Context manager — explicit control ─────────────────────────


@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    async with message.typing():
        await asyncio.sleep(3)  # user sees "typing..."
        result = "Report generated!"
    await message.answer(result)


# ── 3. One-shot — like aiogram's answer_chat_action ───────────────


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    await message.answer_chat_action()  # sends "typing" once
    await asyncio.sleep(1)
    await message.answer("pong!")


# ── Main ──────────────────────────────────────────────────────────


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("Typing action bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
