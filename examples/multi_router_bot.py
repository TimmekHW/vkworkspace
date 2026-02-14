"""
Multi-router bot — demonstrates modular code organization with sub-routers,
chat event handling, and the full range of event types.

Usage:
    python examples/multi_router_bot.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command, ChatTypeFilter
from vkworkspace.types import Message

# ── Admin router ──────────────────────────────────────────────────────

admin_router = Router(name="admin")

ADMIN_IDS = ["admin@company.ru"]


@admin_router.message(Command("kick"))
async def cmd_kick(message: Message, bot: Bot) -> None:
    if message.from_user.user_id not in ADMIN_IDS:
        await message.answer("Admins only.")
        return
    await message.answer("User kicked (demo)")


@admin_router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    await message.answer("Users: 42\nMessages today: 1337")


# ── User router ───────────────────────────────────────────────────────

user_router = Router(name="user")


@user_router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Multi-router bot:\n"
        "/start — this message\n"
        "/stats — admin stats\n"
        "/kick — admin command\n"
        "/dm — only works in private chat\n"
    )


@user_router.message(Command("dm"), ChatTypeFilter("private"))
async def cmd_private(message: Message) -> None:
    await message.answer("This is a private conversation.")


@user_router.message(F.text)
async def echo(message: Message) -> None:
    await message.answer(message.text)


# ── Events router ────────────────────────────────────────────────────

events_router = Router(name="events")


@events_router.new_chat_members()
async def on_join(event) -> None:
    if hasattr(event, "answer"):
        await event.answer("Welcome to the group!")


@events_router.left_chat_members()
async def on_leave(event) -> None:
    if hasattr(event, "answer"):
        await event.answer("Someone left the group.")


@events_router.pinned_message()
async def on_pin(event) -> None:
    if hasattr(event, "answer"):
        await event.answer("Message pinned!")


# ── Main ──────────────────────────────────────────────────────────────

async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()

    # Include all routers — order matters for handler priority
    dp.include_routers(admin_router, user_router, events_router)

    print("Multi-router bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
