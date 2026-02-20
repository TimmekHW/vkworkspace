"""
Proxy & rate-limited bot — demonstrates corporate proxy, rate limiting,
retry on 5xx errors, and SSL verification control.

Usage:
    python examples/features/proxy.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Bot is running through corporate proxy with rate limiting.\n"
        "/flood — send 10 messages (rate limiter will queue them)"
    )


@router.message(Command("flood"))
async def cmd_flood(message: Message, bot: Bot) -> None:
    """Send 10 messages — rate limiter ensures we don't exceed 5 req/sec."""
    await message.answer("Sending 10 messages...")
    for i in range(10):
        await bot.send_text(
            message.chat.chat_id,
            f"Message {i + 1}/10",
        )
    await message.answer("Done! All 10 sent within rate limit.")


@router.message(F.text)
async def echo(message: Message) -> None:
    assert message.text is not None  # guaranteed by F.text filter
    await message.answer(message.text)


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://api.internal.corp/bot/v1",
        rate_limit=5,  # Max 5 requests/sec
        proxy="http://corp-proxy.local:3128",  # Corporate HTTP proxy
        timeout=30.0,  # Request timeout
        retry_on_5xx=3,  # Retry up to 3 times on 5xx errors
        verify_ssl=False,  # Disable SSL for self-signed certs
    )

    dp = Dispatcher()
    dp.include_router(router)

    print("Proxy bot is running (rate_limit=5, proxy, retry_on_5xx=3, verify_ssl=False)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
