"""
Text formatting bot — demonstrates four formatting approaches:

1. String helpers (md.*, html.*) — quick inline formatting
2. Text builder (Bold, Italic, ...) — composable nodes with auto parse_mode
3. FormatBuilder — offset/length formatting via `format` parameter
4. Raw markdown — write **bold** directly with bot's default parse_mode

parse_mode can be set in two places:
    - Bot(parse_mode=ParseMode.HTML) — default for ALL messages
    - message.answer(text, parse_mode=ParseMode.HTML) — override per message

Commands:
    /md       — MarkdownV2 with string helpers
    /html     — HTML with string helpers
    /builder  — Text builder (aiogram-style nodes)
    /format   — FormatBuilder (offset/length)
    /long     — split_text for long messages
    /escape   — safe escaping of user input

Usage:
    python examples/features/formatting.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.enums import ParseMode
from vkworkspace.filters import Command
from vkworkspace.types import Message
from vkworkspace.utils import FormatBuilder
from vkworkspace.utils.text import (
    Bold,
    Code,
    Italic,
    Link,
    Mention,
    Pre,
    Text,
    Underline,
    html,
    md,
    split_text,
)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    content = Text(
        Bold("Text formatting demo bot"),
        "\n\n",
        "/md — MarkdownV2 (string helpers)\n",
        "/html — HTML (string helpers)\n",
        "/builder — Text builder (aiogram-style)\n",
        "/format — FormatBuilder (offset/length)\n",
        "/long — split_text for long messages\n",
        "/escape — safe escaping of user input",
    )
    await message.answer(**content.as_kwargs())


@router.message(Command("md"))
async def cmd_markdown(message: Message) -> None:
    text = "\n".join(
        [
            md.bold("Bold text"),
            md.italic("Italic text"),
            md.underline("Underlined"),
            md.strikethrough("Strikethrough"),
            md.code("inline code"),
            md.pre("x = 42\nprint(x)", "python"),
            md.link("Example link", "https://example.com"),
            md.mention("user@company.ru"),
            md.quote("This is a quote"),
        ]
    )
    # ── Option 2: override per message ──
    # Bot default is HTML, but this specific message uses MarkdownV2
    await message.answer(text, parse_mode=ParseMode.MARKDOWNV2)


@router.message(Command("html"))
async def cmd_html(message: Message) -> None:
    text = "\n".join(
        [
            html.bold("Bold text"),
            html.italic("Italic text"),
            html.underline("Underlined"),
            html.strikethrough("Strikethrough"),
            html.code("inline code"),
            html.pre("x = 42\nprint(x)", "python"),
            html.link("Example link", "https://example.com"),
            html.mention("user@company.ru"),
            html.quote("This is a quote"),
            "",
            html.unordered_list(["Item A", "Item B", "Item C"]),
        ]
    )
    # parse_mode inherited from Bot(parse_mode=HTML) — no need to pass it
    await message.answer(text)


@router.message(Command("builder"))
async def cmd_builder(message: Message) -> None:
    # Text builder: composable nodes with auto-escaping and auto parse_mode
    content = Text(
        Bold("Text Builder Demo"),
        "\n\n",
        "This is ",
        Bold("bold"),
        ", ",
        Italic("italic"),
        ", ",
        Underline("underlined"),
        ", and ",
        Bold(Italic("bold italic")),
        ".\n\n",
        "Inline: ",
        Code("x = 42"),
        "\n",
        Pre("def hello():\n    print('world')", language="python"),
        "\n",
        Link("Example link", url="https://example.com"),
        "\n",
        Mention("user@company.ru"),
    )
    # as_kwargs() returns {"text": "...", "parse_mode": "HTML"} — no need to choose mode
    await message.answer(**content.as_kwargs())

    # Operator chaining also works
    chain = "Price: " + Bold("$99") + " — " + Italic("limited offer!")
    await message.answer(**chain.as_kwargs())

    # Render as MarkdownV2 instead
    simple = Text("Same content, ", Bold("different mode"))
    await message.answer(**simple.as_kwargs("MarkdownV2"))


@router.message(Command("format"))
async def cmd_format(message: Message, bot: Bot) -> None:
    # FormatBuilder: offset/length formatting without markup
    fb = FormatBuilder("Order #42 is ready! Visit https://shop.com")
    fb.bold_text("Order #42")
    fb.italic_text("ready")
    fb.link_text("https://shop.com", url="https://shop.com")
    await bot.send_text(message.chat.chat_id, fb.text, format_=fb.build())


@router.message(Command("long"))
async def cmd_long(message: Message) -> None:
    # Generate a long message (~6000 chars)
    long_text = "\n".join(f"Line {i}: {'A' * 50}" for i in range(1, 101))
    chunks = split_text(long_text)
    # parse_mode=None disables formatting even if Bot has a default
    await message.answer(
        f"Splitting {len(long_text)} chars into {len(chunks)} chunks...",
        parse_mode=None,
    )
    for i, chunk in enumerate(chunks, 1):
        await message.answer(f"[{i}/{len(chunks)}]\n{chunk}")


@router.message(Command("escape"))
async def cmd_escape(message: Message) -> None:
    raw = "Price: $100 & <script>alert('xss')</script> *bold*"

    md_safe = md.escape(raw)
    html_safe = html.escape(raw)

    await message.answer(
        f"Raw input:\n{raw}\n\nmd.escape():\n{md_safe}\n\nhtml.escape():\n{html_safe}"
    )


@router.message(F.text)
async def echo_formatted(message: Message) -> None:
    # Text builder auto-escapes user input — no manual html.escape() needed
    assert message.text is not None  # guaranteed by F.text filter
    content = Bold("You said") + ": " + Text(message.text)
    await message.answer(**content.as_kwargs())


async def main() -> None:
    # ── Option 1: set parse_mode globally on Bot ──
    # Every send_text / answer / reply will use HTML unless overridden
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
        parse_mode=ParseMode.HTML,
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("Formatting bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
