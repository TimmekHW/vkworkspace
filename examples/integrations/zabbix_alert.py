"""
Zabbix -> VK Teams: alerts with feedback chain.

Full cycle:
    1. Zabbix webhook -> BotServer /alert endpoint
    2. Bot sends alert to chat with inline buttons
    3. User clicks "Взял" -> FSM asks: "что делаешь?" -> "сколько минут?"
    4. Bot edits original alert with status
    5. "Эскалация" -> forwards to L2 chat
    6. "Ложная тревога" -> marks as false alarm

Usage:
    python examples/integrations/zabbix_alert.py

    # Simulate Zabbix webhook:
    curl -X POST http://localhost:8080/alert \\
        -H "Content-Type: application/json" \\
        -d '{"event_id": "12345", "host": "db-master-01", \\
             "trigger": "CPU > 95%", "severity": "high"}'

    curl http://localhost:8080/health

Zabbix media type config:
    Type: Webhook
    URL: http://bot-host:8080/alert
    Body: {"event_id":"{EVENT.ID}","host":"{HOST.NAME}",
           "trigger":"{TRIGGER.NAME}","severity":"{TRIGGER.SEVERITY}"}
"""

import logging

from vkworkspace import Bot, BotServer, F, Router
from vkworkspace.filters import Command
from vkworkspace.filters.state import StateFilter
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.types import CallbackQuery, Message
from vkworkspace.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

ONCALL_CHAT = "oncall-infra@chat.corp.ru"
L2_CHAT = "l2-escalation@chat.corp.ru"

server = BotServer(
    token="YOUR_BOT_TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    port=8080,
    # api_key="secret",
    # proxy="http://proxy:8535",
)


# ── FSM: feedback chain after "Взял" ────────────────────────────────

class IncidentFlow(StatesGroup):
    action = State()     # "что делаешь?"
    eta = State()        # "сколько времени?"


# ── HTTP: receive Zabbix webhook ─────────────────────────────────────

@server.route("/alert")
async def on_alert(bot: Bot, data: dict):
    """POST /alert — Zabbix sends event data, bot sends alert to chat."""
    event_id = data["event_id"]
    severity_emoji = {
        "high": "🔴", "average": "🟡", "warning": "🟡",
        "information": "🔵", "info": "🔵",
    }.get(data.get("severity", ""), "⚪")

    text = (
        f"{severity_emoji} <b>Zabbix Alert</b>\n"
        f"Host: {data['host']}\n"
        f"Trigger: {data['trigger']}\n"
        f"Event: #{event_id}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="Взял", callback_data=f"ack:{event_id}")
    kb.button(text="Эскалация", callback_data=f"esc:{event_id}")
    kb.button(text="Ложная тревога", callback_data=f"false:{event_id}")
    kb.adjust(2, 1)

    resp = await bot.send_text(
        ONCALL_CHAT, text,
        parse_mode="HTML",
        inline_keyboard_markup=kb.as_markup(),
    )

    return {"ok": True, "msg_id": resp.msg_id}


# ── Bot: handle button clicks + FSM ─────────────────────────────────

router = Router()


@router.callback_query(F.callback_data.startswith("ack:"))
async def on_ack(query: CallbackQuery, state: FSMContext) -> None:
    """User took the incident — start feedback chain."""
    event_id = query.callback_data.split(":")[1]
    user = query.from_user.nick if query.from_user else "?"

    # Edit alert: remove buttons, show who took it
    if query.message:
        await query.message.edit_text(
            f"{query.message.text}\n\n✅ Взял: {user}",
            parse_mode="HTML",
        )

    # Start FSM chain
    await state.update_data(event_id=event_id)
    await state.set_state(IncidentFlow.action)

    if query.message:
        await query.message.answer(f"{user}, что делаешь?")
    await query.answer()


@router.message(StateFilter(IncidentFlow.action), F.text)
async def on_action(message: Message, state: FSMContext) -> None:
    """Step 1: what are you doing?"""
    await state.update_data(action=message.text)
    await state.set_state(IncidentFlow.eta)
    await message.answer("Сколько времени нужно? (минуты)")


@router.message(StateFilter(IncidentFlow.eta), F.text)
async def on_eta(message: Message, state: FSMContext) -> None:
    """Step 2: ETA — done, log and clear."""
    data = await state.get_data()
    user = message.from_user.nick if message.from_user else "?"

    summary = (
        f"📋 <b>Инцидент #{data.get('event_id', '?')}</b>\n"
        f"Действие: {data.get('action', '?')}\n"
        f"ETA: {message.text} мин\n"
        f"Ответственный: {user}"
    )
    await message.answer(summary, parse_mode="HTML")
    await state.clear()


@router.callback_query(F.callback_data.startswith("esc:"))
async def on_escalate(query: CallbackQuery) -> None:
    """Escalate to L2."""
    event_id = query.callback_data.split(":")[1]
    user = query.from_user.nick if query.from_user else "?"

    if query.message:
        await query.message.edit_text(
            f"{query.message.text}\n\n⚠️ Эскалировано: {user}",
            parse_mode="HTML",
        )
        # Forward to L2 chat
        if query.message.bot:
            await query.message.bot.send_text(
                L2_CHAT, f"⚠️ Инцидент #{event_id} эскалирован с L1",
            )

    await query.answer()


@router.callback_query(F.callback_data.startswith("false:"))
async def on_false_alarm(query: CallbackQuery) -> None:
    """Mark as false alarm."""
    user = query.from_user.nick if query.from_user else "?"

    if query.message:
        await query.message.edit_text(
            f"{query.message.text}\n\n❌ Ложная тревога: {user}",
            parse_mode="HTML",
        )
    await query.answer()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Я Zabbix-бот. Алерты приходят на /alert endpoint.\n"
        "curl -X POST http://host:8080/alert -d '{...}'"
    )


# ── Lifecycle hooks ──────────────────────────────────────────────────

@server.on_startup
async def on_startup():
    me = await server.bot.get_me()
    logging.info("Zabbix bot '%s' started, listening on :%d", me.nick, server.port)


@server.on_shutdown
async def on_shutdown():
    logging.info("Zabbix bot stopped")


# ── Start ────────────────────────────────────────────────────────────

server.include_router(router)

if __name__ == "__main__":
    server.run()
