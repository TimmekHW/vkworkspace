"""
Keyboard bot — demonstrates inline keyboards and callback handling.

Usage:
    python examples/keyboard_bot.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.enums import ButtonStyle
from vkworkspace.filters import Command
from vkworkspace.types import CallbackQuery, Message
from vkworkspace.utils.keyboard import InlineKeyboardBuilder

router = Router()


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="Option A", callback_data="option_a")
    builder.button(text="Option B", callback_data="option_b")
    builder.button(text="Cancel", callback_data="cancel", style=ButtonStyle.ATTENTION)
    builder.adjust(2, 1)  # First row: 2 buttons, second row: 1 button

    await message.answer(
        "Choose an option:",
        inline_keyboard_markup=builder.as_markup(),
    )


@router.callback_query(F.callback_data == "option_a")
async def callback_option_a(query: CallbackQuery) -> None:
    await query.answer("You chose Option A!")


@router.callback_query(F.callback_data == "option_b")
async def callback_option_b(query: CallbackQuery) -> None:
    await query.answer("You chose Option B!")


@router.callback_query(F.callback_data == "cancel")
async def callback_cancel(query: CallbackQuery) -> None:
    await query.answer("Cancelled", show_alert=True)


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("Keyboard bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
