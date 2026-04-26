"""
Filters bot — demonstrates all built-in filter classes.

Covers attachment filters (file/image/video/audio/voice/sticker), mention/sender,
URL detection, callback-data regex with captured groups, and filter composition.

Usage:
    python examples/features/filters.py
"""

from __future__ import annotations

import asyncio
import logging
import os

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import (
    AudioFilter,
    CallbackDataRegexpFilter,
    Command,
    FileFilter,
    ImageFilter,
    MentionFilter,
    SenderFilter,
    StickerFilter,
    URLFilter,
    VideoFilter,
    VoiceFilter,
)
from vkworkspace.types import CallbackQuery, Message
from vkworkspace.utils import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["VK_TEAMS_TOKEN"]
ADMIN = os.environ.get("ADMIN_ID", "admin@example.com")
BOT_ID = os.environ.get("BOT_ID", "bot@example.com")

router = Router()


# ── Attachments ────────────────────────────────────────────────────────────
@router.message(ImageFilter())
async def on_image(message: Message) -> None:
    await message.answer("Got an image!")


@router.message(VideoFilter())
async def on_video(message: Message) -> None:
    await message.answer("Got a video!")


@router.message(AudioFilter())
async def on_audio(message: Message) -> None:
    await message.answer("Got audio!")


@router.message(VoiceFilter())
async def on_voice(message: Message) -> None:
    await message.answer("Got a voice message!")


@router.message(StickerFilter())
async def on_sticker(message: Message) -> None:
    await message.answer("Nice sticker!")


# Catch-all for any other file (after the more-specific filters above didn't match)
@router.message(FileFilter())
async def on_other_file(message: Message) -> None:
    await message.answer("Got a file (not image/video/audio/voice).")


# ── Mention ────────────────────────────────────────────────────────────────
@router.message(MentionFilter(BOT_ID))
async def on_mention(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "there"
    await message.answer(f"You mentioned me, {name}!")


# ── Sender (admin-only command) ────────────────────────────────────────────
@router.message(SenderFilter(ADMIN) & Command("admin"))
async def admin_only(message: Message) -> None:
    await message.answer("Hello, admin. Sender filter passed.")


@router.message(Command("admin"))
async def admin_denied(message: Message) -> None:
    await message.answer("Forbidden. This command is admin-only.")


# ── URL detection — captured into kwargs ───────────────────────────────────
@router.message(URLFilter())
async def on_url(message: Message, url: str) -> None:
    await message.answer(f"Found a link in your message: {url}")


# ── Inline keyboard with callback_data regex ───────────────────────────────
@router.message(Command("orders"))
async def show_orders(message: Message) -> None:
    kb = InlineKeyboardBuilder()
    for order_id in (101, 102, 103):
        kb.button(text=f"Order #{order_id}", callback_data=f"order:{order_id}")
    kb.adjust(1)
    await message.answer("Pick an order:", inline_keyboard_markup=kb.as_markup())


@router.callback_query(CallbackDataRegexpFilter(r"^order:(\d+)$"))
async def on_order_picked(query: CallbackQuery, regexp_match) -> None:
    order_id = regexp_match.group(1)
    await query.answer(f"You picked order #{order_id}", show_alert=True)


# ── Composition: admin + image upload triggers a special handler ───────────
@router.message(SenderFilter(ADMIN) & ImageFilter())
async def admin_image(message: Message) -> None:
    await message.answer("Admin image upload accepted.")


# ── Magic F still works for all of the above ───────────────────────────────
@router.message(F.text == "ping")
async def ping(message: Message) -> None:
    await message.answer("pong")


async def main() -> None:
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
