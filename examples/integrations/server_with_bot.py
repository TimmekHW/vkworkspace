"""
BotServer — bot as an HTTP service for non-Python integrations.

NOT a webhook receiver. BotServer lets external systems (PHP, Go, N8N,
Grafana, Zabbix, any language) call the bot via simple HTTP requests.
They send JSON → the bot delivers messages, buttons, and files to VK Teams.

For Python apps you don't need BotServer — use Bot directly::

    from vkworkspace import Bot
    bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
    await bot.send_text("user@corp.ru", "Hello!")

Or run Dispatcher in the background of your FastAPI/Django/Flask app.

Usage:
    python examples/integrations/server_with_bot.py

    curl -X POST http://localhost:8080/send -H "Content-Type: application/json" \
        -d '{"email": "user@corp.ru", "text": "Hello!"}'

    curl -X POST http://localhost:8080/alert -H "Content-Type: application/json" \
        -d '{"email": "admin@corp.ru", "text": "CPU > 95%"}'

    curl http://localhost:8080/health
"""

from vkworkspace import Bot, BotServer, F, Router
from vkworkspace.filters import Command
from vkworkspace.filters.state import StateFilter
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.types import CallbackQuery, Message
from vkworkspace.utils.keyboard import InlineKeyboardBuilder

server = BotServer(
    token="YOUR_BOT_TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    port=8080,
    # api_key="secret",        # require X-Api-Key header
    # proxy="http://proxy:8535",
    # rate_limit=10,
)


# ── HTTP routes (for external systems) ────────────────────────────────


@server.route("/send")
async def send(bot: Bot, data: dict):
    """POST /send {"email": "...", "text": "..."}"""
    await bot.send_text(data["email"], data["text"])


@server.route("/alert")
async def alert(bot: Bot, data: dict):
    """POST /alert {"email": "...", "text": "..."} — with inline buttons"""
    kb = InlineKeyboardBuilder()
    kb.button(text="Взял", callback_data="ack")
    kb.button(text="Эскалация", callback_data="esc")
    kb.adjust(2)
    await bot.send_text(
        data["email"],
        f"🔴 {data['text']}",
        inline_keyboard_markup=kb.as_markup(),
    )


@server.route("/status", methods=["GET"])
async def status(bot: Bot, data: dict):
    """GET /status — bot info"""
    me = await bot.get_me()
    return {"ok": True, "bot": me.nick}


# ── Optional: VK Teams event handlers (enables polling) ──────────────
# Uncomment to also handle messages/buttons from users in VK Teams.
# server.include_router(router) starts polling alongside the HTTP server.

router = Router()


class Incident(StatesGroup):
    comment = State()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Привет! Я бот мониторинга. Жду алерты.")


@router.callback_query(F.callback_data == "ack")
async def on_ack(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Incident.comment)
    if query.message:
        await query.message.answer("Опиши что делаешь:")
    await query.answer()


@router.callback_query(F.callback_data == "esc")
async def on_esc(query: CallbackQuery) -> None:
    if query.message:
        await query.message.answer("Эскалировано на L2")
    await query.answer()


@router.message(StateFilter(Incident.comment), F.text)
async def on_comment(message: Message, state: FSMContext) -> None:
    await message.answer(f"Зафиксировано: {message.text}")
    await state.clear()


# Подключаем polling — теперь server.run() запускает и HTTP, и бота
server.include_router(router)

if __name__ == "__main__":
    server.run()
