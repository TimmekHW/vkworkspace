"""
ChatOps bot — run infrastructure commands from VK Teams.

Features:
    - /status, /logs, /restart, /deploy commands with RBAC
    - Scheduled health checks and daily reports
    - Audit log of all executed commands
    - Docker-ready: BotServer provides /health endpoint
    - Per-command role-based access control via middleware

Usage:
    python examples/integrations/chatops.py

    # Docker:
    HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1

    # Trigger deploy from CI/CD:
    curl -X POST http://localhost:8080/deploy \\
        -H "X-Api-Key: secret" \\
        -H "Content-Type: application/json" \\
        -d '{"service": "api-gateway", "tag": "v2.1.0", "chat_id": "devops@chat.corp.ru"}'

Roles:
    l1 — all users:  /status, /logs
    l2 — operators:  /restart
    l3 — admins:     /deploy

Scheduler:
    - Every 5 min: check service health
    - Daily 09:00: morning status report
    - Friday 18:00: weekly incident summary
"""

import logging
from datetime import datetime
from typing import Any

from vkworkspace import BaseMiddleware, Bot, BotServer, F, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message
from vkworkspace.utils.scheduler import Scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEAM_CHAT = "infra-team@chat.corp.ru"

server = BotServer(
    token="YOUR_BOT_TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    port=8080,
    api_key="secret",
    # proxy="http://proxy:8535",
)


# ── RBAC middleware ──────────────────────────────────────────────────

ROLES: dict[str, str] = {
    "admin@corp.ru": "l3",
    "devops-lead@corp.ru": "l3",
    "operator1@corp.ru": "l2",
    "operator2@corp.ru": "l2",
    # everyone else → "l1"
}

ROLE_HIERARCHY = {"l1": 1, "l2": 2, "l3": 3}

COMMAND_ROLES: dict[str, str] = {
    "status": "l1",
    "logs": "l1",
    "restart": "l2",
    "deploy": "l3",
}


class RBACMiddleware(BaseMiddleware):
    """Per-command role-based access control.

    Checks user role against command requirements.
    Passes ``role`` and ``audit`` into handler data for DI.
    """

    async def __call__(
        self,
        handler: Any,
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        # Inject role into handler data
        user_id = ""
        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.user_id or ""

        role = ROLES.get(user_id, "l1")
        data["role"] = role

        # Check command RBAC
        command = data.get("command")
        if command:
            required = COMMAND_ROLES.get(command.command, "l1")
            user_level = ROLE_HIERARCHY.get(role, 0)
            required_level = ROLE_HIERARCHY.get(required, 0)

            if user_level < required_level:
                nick = ""
                if hasattr(event, "from_user") and event.from_user:
                    nick = event.from_user.nick or user_id
                logger.warning(
                    "ACCESS DENIED: %s (%s) tried /%s (requires %s)",
                    nick,
                    role,
                    command.command,
                    required,
                )
                if hasattr(event, "answer"):
                    await event.answer(
                        f"Нет доступа. /{command.command} требует роль {required}+, у тебя {role}."
                    )
                return None

        # Audit log
        if command and hasattr(event, "from_user") and event.from_user:
            nick = event.from_user.nick or user_id
            logger.info(
                "AUDIT: %s (%s) executed /%s %s",
                nick,
                role,
                command.command,
                command.args or "",
            )

        return await handler(event, data)


# ── Scheduler ────────────────────────────────────────────────────────

scheduler = Scheduler()

SERVICES = ["api-gateway", "auth-service", "payment", "notification"]


@scheduler.interval(seconds=300)
async def health_check(bot: Bot) -> None:
    """Check service health every 5 minutes."""
    # In real code: query Prometheus / Kubernetes / Docker API
    down = [s for s in SERVICES if not _is_healthy(s)]
    if down:
        await bot.send_text(
            TEAM_CHAT,
            f"<b>Health check failed</b>\nDown: {', '.join(down)}",
            parse_mode="HTML",
        )


@scheduler.daily(hour=9, minute=0)
async def morning_report(bot: Bot) -> None:
    """Daily status report at 09:00."""
    lines = [f"<b>Morning Report — {datetime.now():%Y-%m-%d}</b>\n"]
    for svc in SERVICES:
        status = "OK" if _is_healthy(svc) else "DOWN"
        lines.append(f"  {svc}: {status}")
    await bot.send_text(TEAM_CHAT, "\n".join(lines), parse_mode="HTML")


@scheduler.weekly(weekday=4, hour=18)
async def weekly_summary(bot: Bot) -> None:
    """Friday 18:00 — weekly incident count."""
    await bot.send_text(
        TEAM_CHAT,
        "<b>Weekly Summary</b>\nIncidents: 3 (2 resolved, 1 ongoing)\nDeploys: 12\nUptime: 99.7%",
        parse_mode="HTML",
    )


def _is_healthy(service: str) -> bool:
    """Stub — replace with real health check."""
    return service != "payment"  # payment is always "down" for demo


# ── Bot commands ─────────────────────────────────────────────────────

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>ChatOps Bot</b>\n\n"
        "/status [service] — health status\n"
        "/logs service [lines] — recent logs\n"
        "/restart service — restart (L2+)\n"
        "/deploy service tag — deploy (L3+)\n"
        "/help — this message",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, role: str) -> None:
    """role is injected by RBACMiddleware."""
    level = ROLE_HIERARCHY.get(role, 0)
    lines = ["<b>Available commands</b> (your role: {role})\n"]

    for cmd, req in sorted(COMMAND_ROLES.items()):
        req_level = ROLE_HIERARCHY.get(req, 0)
        lock = "" if level >= req_level else " (locked)"
        lines.append(f"  /{cmd}{lock}")

    await message.answer(
        "\n".join(lines).format(role=role),
        parse_mode="HTML",
    )


@router.message(Command("status"))
async def cmd_status(message: Message, command: Any) -> None:
    """Show service health. All users can run this."""
    target = (command.args or "").strip()

    if target:
        status = "OK" if _is_healthy(target) else "DOWN"
        await message.answer(f"{target}: {status}")
        return

    # All services
    lines = ["<b>Service Status</b>\n"]
    for svc in SERVICES:
        emoji = "🟢" if _is_healthy(svc) else "🔴"
        lines.append(f"  {emoji} {svc}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("logs"))
async def cmd_logs(message: Message, command: Any) -> None:
    """Show recent logs. /logs api-gateway 50"""
    args = (command.args or "").strip().split()
    if not args:
        await message.answer("Usage: /logs service [lines]\nExample: /logs api-gateway 50")
        return

    service = args[0]
    n = int(args[1]) if len(args) > 1 else 20

    if service not in SERVICES:
        await message.answer(f"Unknown service: {service}")
        return

    # Stub — replace with kubectl logs / docker logs / journalctl
    fake_logs = "\n".join(
        f"2024-01-15 10:{i:02d}:00 INFO request handled" for i in range(min(n, 10))
    )
    await message.answer(f"<code>{fake_logs}</code>", parse_mode="HTML")


@router.message(Command("restart"))
async def cmd_restart(message: Message, command: Any) -> None:
    """Restart a service. Requires L2+."""
    service = (command.args or "").strip()
    if not service:
        await message.answer("Usage: /restart service\nExample: /restart payment")
        return

    if service not in SERVICES:
        await message.answer(f"Unknown service: {service}")
        return

    async with message.typing():
        # Stub — replace with kubectl rollout restart / docker restart
        import asyncio

        await asyncio.sleep(2)

    await message.answer(f"Restarted {service}")


@router.message(Command("deploy"))
async def cmd_deploy(message: Message, command: Any) -> None:
    """Deploy a service. Requires L3+. /deploy api-gateway v2.1.0"""
    args = (command.args or "").strip().split()
    if len(args) != 2:
        await message.answer("Usage: /deploy service tag\nExample: /deploy api-gateway v2.1.0")
        return

    service, tag = args

    if service not in SERVICES:
        await message.answer(f"Unknown service: {service}")
        return

    async with message.typing():
        # Stub — replace with kubectl set image / helm upgrade / etc.
        import asyncio

        await asyncio.sleep(3)

    user = message.from_user.nick if message.from_user else "?"
    await message.answer(
        f"<b>Deployed</b>\nService: {service}\nTag: {tag}\nBy: {user}",
        parse_mode="HTML",
    )

    # Notify team chat
    if message.bot:
        await message.bot.send_text(
            TEAM_CHAT,
            f"Deploy: {service} → {tag} by {user}",
        )


@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Unknown command. /help for list.")


# ── HTTP routes (CI/CD integration) ─────────────────────────────────


@server.route("/deploy")
async def http_deploy(bot: Bot, data: dict) -> dict[str, Any]:
    """POST /deploy — trigger deploy from CI/CD pipeline.

    Body: {"service": "api-gateway", "tag": "v2.1.0", "chat_id": "..."}
    Protected by X-Api-Key header (set in BotServer constructor).
    """
    service = data.get("service", "?")
    tag = data.get("tag", "?")
    chat_id = data.get("chat_id", TEAM_CHAT)

    await bot.send_text(
        chat_id,
        f"<b>CI/CD Deploy</b>\nService: {service}\nTag: {tag}",
        parse_mode="HTML",
    )
    return {"ok": True, "service": service, "tag": tag}


# ── Lifecycle ────────────────────────────────────────────────────────


@server.on_startup
async def on_startup() -> None:
    me = await server.bot.get_me()
    scheduler.start(server.bot)
    logger.info("ChatOps bot '%s' started, %d jobs scheduled", me.nick, len(scheduler.jobs))


@server.on_shutdown
async def on_shutdown() -> None:
    await scheduler.stop()
    logger.info("ChatOps bot stopped")


# ── Start ────────────────────────────────────────────────────────────

# Register RBAC on all observer types
router.message.middleware.register(RBACMiddleware())
router.callback_query.middleware.register(RBACMiddleware())

server.include_router(router)

if __name__ == "__main__":
    server.run()
    # Docker health: GET http://localhost:8080/health
    # Routes: POST /deploy (with X-Api-Key)
