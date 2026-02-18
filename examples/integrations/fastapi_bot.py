"""
FastAPI + vkworkspace — bot inside an existing web application.

Full pattern:
    1. Bot runs as a background task alongside FastAPI
    2. FastAPI endpoints and bot handlers share the same Bot instance
    3. Custom middleware injects dependencies (DB, Redis) into bot handlers
    4. Proper startup/shutdown via FastAPI lifespan

Usage:
    pip install fastapi uvicorn
    uvicorn examples.integrations.fastapi_bot:app --reload

    # Send notification via API:
    curl -X POST http://localhost:8000/notify \
        -H "Content-Type: application/json" \
        -d '{"email": "user@corp.ru", "text": "Your shift starts now!"}'

    # Meanwhile, bot responds to /start and /duty in VK Teams.

Key points:
    - handle_signals=False: uvicorn manages SIGINT/SIGTERM, not the dispatcher
    - close_bot_on_stop=False: bot session stays alive for FastAPI endpoints
    - Bot as context manager: session auto-closes on shutdown
    - Middleware DI: pass db/redis/config to bot handlers via data dict
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from vkworkspace import BaseMiddleware, Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.types import Message

# ── Fake DB for demo (replace with SQLAlchemy / Redis / etc.) ─────────

DUTY_SCHEDULE: dict[str, str] = {
    "monday": "alice@corp.ru",
    "tuesday": "bob@corp.ru",
    "wednesday": "charlie@corp.ru",
}


class FakeDB:
    """Simulates an async database session."""

    async def get_duty(self, day: str) -> str | None:
        return DUTY_SCHEDULE.get(day)

    async def set_duty(self, day: str, email: str) -> None:
        DUTY_SCHEDULE[day] = email


# ── Middleware: inject dependencies into bot handlers ─────────────────

class DepsMiddleware(BaseMiddleware):
    """Inject app dependencies into every bot handler.

    Any parameter name matching a key in ``data`` dict will be
    auto-injected into the handler (like aiogram's middleware data).

    Example handler::

        @router.message(Command("duty"))
        async def show_duty(message: Message, db: FakeDB, config: dict):
            # db and config are injected by this middleware
            ...
    """

    def __init__(self, db: FakeDB, config: dict[str, Any]) -> None:
        self.db = db
        self.config = config

    async def __call__(
        self,
        handler: Any,
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["config"] = self.config
        return await handler(event, data)


# ── FSM ──────────────────────────────────────────────────────────────

class DutySwap(StatesGroup):
    confirm = State()


# ── Bot handlers ─────────────────────────────────────────────────────

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Команды:\n"
        "/duty monday — кто дежурит\n"
        "/swap monday alice@corp.ru — поменять дежурного"
    )


@router.message(Command("duty"))
async def cmd_duty(message: Message, command: Any, db: FakeDB) -> None:
    """Show who's on duty. `db` is injected by DepsMiddleware."""
    day = command.args.strip().lower() if command.args else ""
    if not day:
        await message.answer("Укажи день: /duty monday")
        return

    duty = await db.get_duty(day)
    if duty:
        await message.answer(f"{day.title()}: {duty}")
    else:
        await message.answer(f"На {day} дежурных нет.")


@router.message(Command("swap"))
async def cmd_swap(
    message: Message, command: Any, db: FakeDB, state: FSMContext,
) -> None:
    """Start duty swap. `db` and `state` both injected."""
    args = (command.args or "").strip().split()
    if len(args) != 2:
        await message.answer("Формат: /swap monday alice@corp.ru")
        return

    day, new_email = args
    await state.update_data(day=day.lower(), new_email=new_email)
    await state.set_state(DutySwap.confirm)
    await message.answer(f"Поменять дежурного на {day} → {new_email}? (да/нет)")


@router.message(F.text.lower() == "да")
async def confirm_swap(message: Message, state: FSMContext, db: FakeDB) -> None:
    data = await state.get_data()
    if not data.get("day"):
        return
    await db.set_duty(data["day"], data["new_email"])
    await message.answer(f"Готово! {data['day'].title()}: {data['new_email']}")
    await state.clear()


@router.message(F.text.lower() == "нет")
async def cancel_swap(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


# ── FastAPI app ──────────────────────────────────────────────────────

# Import here so the example runs even without fastapi installed
# (you'll get ImportError only when actually starting uvicorn)
from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class NotifyRequest(BaseModel):
    email: str
    text: str


# Shared state — created in lifespan, used by both FastAPI and bot
bot: Bot | None = None
dp: Dispatcher | None = None
db: FakeDB | None = None
_polling_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: launch bot polling. Shutdown: stop polling, close bot."""
    global bot, dp, db, _polling_task

    db = FakeDB()
    config = {"app_name": "DutyBot", "version": "1.0"}

    # Bot as context manager — session auto-closes on exit
    async with Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
        # proxy="http://proxy:8535",
    ) as _bot:
        bot = _bot
        dp = Dispatcher()

        # Register middleware with dependencies
        deps = DepsMiddleware(db=db, config=config)
        router.message.middleware.register(deps)
        router.callback_query.middleware.register(deps)

        dp.include_router(router)

        # Start polling as background task:
        #   handle_signals=False    → uvicorn manages SIGINT/SIGTERM
        #   close_bot_on_stop=False → we close bot ourselves via context manager
        _polling_task = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False, close_bot_on_stop=False)
        )

        yield  # FastAPI is running

        # Shutdown: stop polling, bot.close() handled by context manager
        await dp.stop()
        _polling_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _polling_task


app = FastAPI(title="DutyBot API", lifespan=lifespan)


@app.post("/notify")
async def notify(req: NotifyRequest) -> dict[str, bool]:
    """Send a message to VK Teams from any external system."""
    if bot is None:
        return {"ok": False}
    await bot.send_text(req.email, req.text)
    return {"ok": True}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "bot_running": dp.is_running if dp else False,
        "schedule": DUTY_SCHEDULE,
    }
