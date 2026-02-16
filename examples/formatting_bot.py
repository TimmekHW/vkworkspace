"""
Text formatting bot — demonstrates MarkdownV2, HTML, and split_text utilities.

Commands:
    /md       — send a MarkdownV2-formatted message
    /html     — send an HTML-formatted message
    /long     — generate a long message and send it in chunks via split_text
    /escape   — show how md.escape() and html.escape() protect user input

Usage:
    python examples/formatting_bot.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message
from vkworkspace.utils.text import html, md, split_text

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Text formatting demo bot.\n\n"
        "/md — MarkdownV2 example\n"
        "/html — HTML example\n"
        "/long — split_text for long messages\n"
        "/escape — safe escaping of user input"
    )


@router.message(Command("md"))
async def cmd_markdown(message: Message) -> None:
    text = "\n".join([
        md.bold("Bold text"),
        md.italic("Italic text"),
        md.underline("Underlined"),
        md.strikethrough("Strikethrough"),
        md.code("inline code"),
        md.pre("x = 42\nprint(x)", "python"),
        md.link("Example link", "https://example.com"),
        md.quote("This is a quote"),
    ])
    await message.answer(text, parse_mode="MarkdownV2")


@router.message(Command("html"))
async def cmd_html(message: Message) -> None:
    text = "\n".join([
        html.bold("Bold text"),
        html.italic("Italic text"),
        html.underline("Underlined"),
        html.strikethrough("Strikethrough"),
        html.code("inline code"),
        html.pre("x = 42\nprint(x)", "python"),
        html.link("Example link", "https://example.com"),
        html.quote("This is a quote"),
        "",
        html.unordered_list(["Item A", "Item B", "Item C"]),
    ])
    await message.answer(text, parse_mode="HTML")


@router.message(Command("long"))
async def cmd_long(message: Message) -> None:
    # Generate a long message (~6000 chars)
    long_text = "\n".join(
        f"Line {i}: {'A' * 50}" for i in range(1, 101)
    )
    chunks = split_text(long_text)
    await message.answer(f"Splitting {len(long_text)} chars into {len(chunks)} chunks...")
    for i, chunk in enumerate(chunks, 1):
        await message.answer(f"[{i}/{len(chunks)}]\n{chunk}")


@router.message(Command("escape"))
async def cmd_escape(message: Message) -> None:
    raw = "Price: $100 & <script>alert('xss')</script> *bold*"

    md_safe = md.escape(raw)
    html_safe = html.escape(raw)

    await message.answer(
        f"Raw input:\n{raw}\n\n"
        f"md.escape():\n{md_safe}\n\n"
        f"html.escape():\n{html_safe}"
    )


@router.message(F.text)
async def echo_formatted(message: Message) -> None:
    # Echo back user text with both formatting styles
    user_text = message.text
    await message.answer(
        f"{html.bold('You said')}: {html.escape(user_text)}",
        parse_mode="HTML",
    )


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("Formatting bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
