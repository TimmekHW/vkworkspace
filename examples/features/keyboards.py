"""
Keyboard bot — inline keyboards, callbacks, and CallbackDataFactory.

Demonstrates:
  /menu    — simple buttons with F.callback_data == "..."
  /catalog — structured CallbackDataFactory (typed, no string parsing)
  /fruits  — paginated list with ◀ / ▶ navigation

Usage:
    python examples/features/keyboards.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.enums import ButtonStyle
from vkworkspace.filters import CallbackDataFactory, Command
from vkworkspace.types import CallbackQuery, Message
from vkworkspace.utils.keyboard import InlineKeyboardBuilder
from vkworkspace.utils.paginator import PaginationCB, Paginator

router = Router()


# ── 1. Simple approach: raw strings ─────────────────────────────────


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="Option A", callback_data="option_a")
    builder.button(text="Option B", callback_data="option_b")
    builder.button(text="Cancel", callback_data="cancel", style=ButtonStyle.ATTENTION)
    builder.adjust(2, 1)

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


# ── 2. CallbackDataFactory: typed, structured, no manual parsing ────


class ProductCB(CallbackDataFactory, prefix="product"):
    action: str   # "buy", "info", "fav"
    id: int       # product ID


@router.message(Command("catalog"))
async def cmd_catalog(message: Message) -> None:
    products = [(1, "Laptop"), (2, "Phone"), (3, "Tablet")]

    builder = InlineKeyboardBuilder()
    for pid, name in products:
        builder.button(
            text=f"{name} — Info",
            callback_data=ProductCB(action="info", id=pid).pack(),
        )
        builder.button(
            text="Buy",
            callback_data=ProductCB(action="buy", id=pid).pack(),
        )
    builder.adjust(2)  # 2 buttons per row: [Info] [Buy]

    await message.answer(
        "Our products:",
        inline_keyboard_markup=builder.as_markup(),
    )


@router.callback_query(ProductCB.filter(F.action == "info"))
async def on_product_info(query: CallbackQuery, callback_data: ProductCB) -> None:
    await query.answer(f"Product #{callback_data.id} details")


@router.callback_query(ProductCB.filter(F.action == "buy"))
async def on_product_buy(query: CallbackQuery, callback_data: ProductCB) -> None:
    await query.answer(f"Added product #{callback_data.id} to cart!", show_alert=True)


# ── 3. Filter without rule — catch all ProductCB callbacks ───────────
# Uncomment to handle any unmatched product action:
#
# @router.callback_query(ProductCB.filter())
# async def on_product_fallback(query: CallbackQuery, callback_data: ProductCB) -> None:
#     await query.answer(f"Unknown action: {callback_data.action}")


# ── 4. Paginator: list with ◀ / ▶ navigation ────────────────────────

FRUITS = [
    "Apple", "Banana", "Cherry", "Date", "Elderberry",
    "Fig", "Grape", "Honeydew", "Kiwi", "Lemon",
    "Mango", "Nectarine", "Orange", "Papaya", "Quince",
]


def _build_fruits_page(page: int) -> tuple[str, list[list[dict[str, str]]]]:
    """Build text + keyboard for a given page."""
    paginator = Paginator(data=FRUITS, per_page=5, current_page=page, name="fruits")

    lines = [f"Fruits (page {page + 1}/{paginator.total_pages}):"]
    builder = InlineKeyboardBuilder()
    for i, fruit in enumerate(paginator.page_data, paginator.offset + 1):
        lines.append(f"  {i}. {fruit}")
        builder.button(text=fruit, callback_data=f"fruit:{fruit}")
    builder.adjust(1)
    paginator.add_nav_row(builder)

    return "\n".join(lines), builder.as_markup()


@router.message(Command("fruits"))
async def cmd_fruits(message: Message) -> None:
    text, markup = _build_fruits_page(0)
    await message.answer(text, inline_keyboard_markup=markup)


@router.callback_query(PaginationCB.filter(F.name == "fruits"))
async def on_fruits_page(query: CallbackQuery, callback_data: PaginationCB) -> None:
    text, markup = _build_fruits_page(callback_data.page)
    if query.message:
        await query.message.edit_text(text, inline_keyboard_markup=markup)
    await query.answer()


# ── Main ────────────────────────────────────────────────────────────


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
