"""
RedisListener — consume tasks from Redis Streams.

Any system that writes to Redis (PHP, Go, Python, N8N) can send
tasks to the bot. Redis Streams give reliable delivery with
acknowledgment, retry, and dead letter handling.

Usage:
    python examples/integrations/redis_listener.py

    # Send a task from any Redis client:
    redis-cli XADD bot:tasks '*' chat_id 'user@corp.ru' text 'Hello!'

    # Send an alert:
    redis-cli XADD bot:alerts '*' chat_id 'admin@corp.ru' text 'CPU > 95%' level critical

    # PHP side:
    # $redis->xAdd("bot:tasks", "*", ["chat_id" => "user@corp.ru", "text" => "Hello!"]);
"""

from pydantic import BaseModel

from vkworkspace import F, RedisListener, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message
from vkworkspace.utils.keyboard import InlineKeyboardBuilder

# ── Pydantic models for data validation ──────────────────────────────

class TaskPayload(BaseModel):
    chat_id: str
    text: str


class AlertPayload(BaseModel):
    chat_id: str
    text: str
    level: str = "warning"


# ── Listener setup ───────────────────────────────────────────────────

listener = RedisListener(
    token="YOUR_BOT_TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    redis_url="redis://localhost:6379",
    # group="my-workers",       # consumer group name
    # consumer="worker-1",      # this worker's name
    # max_retries=5,            # retries before dead letter
    # retry_after=60,           # seconds between retries
)


# ── Lifecycle hooks ──────────────────────────────────────────────────

@listener.on_startup
async def on_startup():
    me = await listener.bot.get_me()
    print(f"Listener started as {me.nick}, consuming streams...")


@listener.on_shutdown
async def on_shutdown():
    print("Listener stopped, cleanup done.")


# ── Stream handlers ──────────────────────────────────────────────────

@listener.handler("bot:tasks", model=TaskPayload)
async def on_task(bot, data: TaskPayload):
    """Simple text message."""
    await bot.send_text(data.chat_id, data.text)


@listener.handler("bot:alerts", model=AlertPayload)
async def on_alert(bot, data: AlertPayload):
    """Alert with inline buttons."""
    emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(data.level, "⚪")
    kb = InlineKeyboardBuilder()
    kb.button(text="Взял", callback_data="ack")
    kb.button(text="Эскалация", callback_data="esc")
    kb.adjust(2)
    await bot.send_text(
        data.chat_id,
        f"{emoji} {data.text}",
        inline_keyboard_markup=kb.as_markup(),
    )


# ── Optional: VK Teams event handlers ───────────────────────────────
# Uncomment to also handle messages from users in VK Teams.
# listener.include_router(router) starts polling alongside Redis.

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Привет! Я слушаю Redis и VK Teams одновременно.")


@router.message(F.text)
async def echo(message: Message) -> None:
    await message.answer(f"Эхо: {message.text}")


listener.include_router(router)

if __name__ == "__main__":
    listener.run()
