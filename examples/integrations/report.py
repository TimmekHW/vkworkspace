"""
BI Report Bot — scheduled reports and on-demand queries from VK Teams.

Pattern for BI/analytics teams working with synchronous databases
(Oracle, PostgreSQL, MySQL) and heavy libraries (pandas, openpyxl).

Features:
    - Scheduled daily/weekly reports with Excel attachments
    - On-demand /report and /kpi commands
    - run_sync() for Oracle/pandas calls without blocking the event loop
    - Scheduler with DI: db pool passed to job functions automatically
    - Typing indicator while reports generate

Usage:
    pip install cx_Oracle openpyxl pandas  # or oracledb
    python examples/integrations/report.py

Commands:
    /kpi          — current KPI summary (text)
    /report sales — generate Excel report, send as file
    /etl          — ETL pipeline status
"""

import asyncio
import logging
from datetime import datetime
from io import BytesIO
from typing import Any

from vkworkspace import Bot, Dispatcher, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message
from vkworkspace.types.input_file import InputFile
from vkworkspace.utils.scheduler import Scheduler
from vkworkspace.utils.sync import run_sync, sync_to_async
from vkworkspace.utils.text import split_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REPORTS_CHAT = "bi-reports@chat.corp.ru"
ALERTS_CHAT = "bi-alerts@chat.corp.ru"


# ── Fake Oracle layer (replace with real cx_Oracle / oracledb) ───────

class FakeOraclePool:
    """Simulates a synchronous Oracle connection pool.

    Replace with real cx_Oracle::

        import cx_Oracle
        pool = cx_Oracle.SessionPool(
            user="BI_USER", password="***",
            dsn="host:1521/DWDB", min=2, max=10,
        )
    """

    def query_kpi(self) -> dict[str, Any]:
        """Synchronous — blocks the thread. That's why we use run_sync()."""
        import time
        time.sleep(0.5)  # simulate Oracle query latency
        return {
            "revenue": 142_500_000,
            "clients_new": 1_247,
            "npl_rate": 3.2,
            "deposits": 89_700_000,
            "cards_issued": 3_891,
        }

    def query_sales(self, month: str | None = None) -> list[dict[str, Any]]:
        """Synchronous — returns raw rows for Excel."""
        import time
        time.sleep(1.0)  # simulate heavy query
        return [
            {"dept": "Enterprise", "revenue": 52_000_000, "deals": 87, "avg_deal": 597_701},
            {"dept": "SMB", "revenue": 21_000_000, "deals": 412, "avg_deal": 50_971},
            {"dept": "Retail", "revenue": 45_000_000, "deals": 12_450, "avg_deal": 3_614},
            {"dept": "Digital", "revenue": 24_500_000, "deals": 8_900, "avg_deal": 2_753},
        ]

    def query_etl_status(self) -> list[dict[str, Any]]:
        """ETL pipeline status."""
        return [
            {"pipeline": "stg_transactions", "status": "OK", "rows": 1_240_000, "duration": "4m12s"},
            {"pipeline": "stg_clients", "status": "OK", "rows": 47_000, "duration": "1m03s"},
            {"pipeline": "dm_sales", "status": "FAIL", "rows": 0, "duration": "0m00s"},
            {"pipeline": "dm_risk", "status": "OK", "rows": 890_000, "duration": "8m45s"},
        ]


# ── Sync-to-async wrappers ──────────────────────────────────────────

@sync_to_async
def build_excel(rows: list[dict[str, Any]], title: str) -> bytes:
    """Build Excel report in memory. Synchronous (openpyxl is sync).

    Replace with real openpyxl::

        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = title
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append(list(row.values()))
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()
    """
    # Stub: generate CSV-like bytes (replace with real openpyxl)
    buf = BytesIO()
    if rows:
        header = "\t".join(rows[0].keys()) + "\n"
        buf.write(header.encode("utf-8"))
        for row in rows:
            line = "\t".join(str(v) for v in row.values()) + "\n"
            buf.write(line.encode("utf-8"))
    return buf.getvalue()


# ── Scheduler: automated reports ─────────────────────────────────────

scheduler = Scheduler()


@scheduler.daily(hour=9, minute=0)
async def morning_kpi(bot: Bot, db: FakeOraclePool) -> None:
    """Daily KPI report at 09:00. `db` injected by scheduler.start()."""
    kpi = await run_sync(db.query_kpi)
    text = (
        f"<b>KPI — {datetime.now():%d.%m.%Y}</b>\n\n"
        f"Выручка: {kpi['revenue']:,.0f} ₽\n"
        f"Новых клиентов: {kpi['clients_new']:,}\n"
        f"NPL: {kpi['npl_rate']}%\n"
        f"Вклады: {kpi['deposits']:,.0f} ₽\n"
        f"Карт выдано: {kpi['cards_issued']:,}"
    )
    await bot.send_text(REPORTS_CHAT, text, parse_mode="HTML")


@scheduler.daily(hour=9, minute=5)
async def morning_excel(bot: Bot, db: FakeOraclePool) -> None:
    """Daily Excel at 09:05 — detailed sales breakdown."""
    rows = await run_sync(db.query_sales)
    excel = await build_excel(rows, title="Daily Sales")
    date_str = datetime.now().strftime("%Y-%m-%d")
    await bot.send_file(
        REPORTS_CHAT,
        file=InputFile(excel, filename=f"sales_{date_str}.xlsx"),
        caption=f"Продажи за {date_str}",
    )


@scheduler.interval(seconds=300)
async def etl_watchdog(bot: Bot, db: FakeOraclePool) -> None:
    """Check ETL every 5 min. Alert on failures."""
    statuses = await run_sync(db.query_etl_status)
    failed = [s for s in statuses if s["status"] != "OK"]
    if failed:
        lines = ["<b>ETL ALERT</b>\n"]
        for s in failed:
            lines.append(f"  {s['pipeline']}: {s['status']}")
        await bot.send_text(ALERTS_CHAT, "\n".join(lines), parse_mode="HTML")


@scheduler.weekly(weekday=0, hour=10)
async def monday_summary(bot: Bot, db: FakeOraclePool) -> None:
    """Monday 10:00 — weekly summary with Excel."""
    rows = await run_sync(db.query_sales)
    excel = await build_excel(rows, title="Weekly Sales")
    await bot.send_file(
        REPORTS_CHAT,
        file=InputFile(excel, filename="weekly_sales.xlsx"),
        caption="Еженедельный отчёт по продажам",
    )


# ── Bot commands ─────────────────────────────────────────────────────

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>BI Report Bot</b>\n\n"
        "/kpi — текущие метрики\n"
        "/report — Excel-отчёт по продажам\n"
        "/etl — статус ETL-пайплайнов",
        parse_mode="HTML",
    )


@router.message(Command("kpi"))
async def cmd_kpi(message: Message, bot: Bot) -> None:
    """On-demand KPI. Oracle query runs in thread via run_sync()."""
    async with message.typing():
        kpi = await run_sync(db.query_kpi)

    text = (
        f"<b>KPI — {datetime.now():%H:%M}</b>\n\n"
        f"Выручка: {kpi['revenue']:,.0f} ₽\n"
        f"Новых клиентов: {kpi['clients_new']:,}\n"
        f"NPL: {kpi['npl_rate']}%\n"
        f"Вклады: {kpi['deposits']:,.0f} ₽\n"
        f"Карт выдано: {kpi['cards_issued']:,}"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("report"))
async def cmd_report(message: Message, bot: Bot) -> None:
    """On-demand Excel report."""
    async with message.typing():
        rows = await run_sync(db.query_sales)
        excel = await build_excel(rows, title="Sales Report")

    date_str = datetime.now().strftime("%Y-%m-%d")
    await message.answer_file(
        file=InputFile(excel, filename=f"sales_{date_str}.xlsx"),
        caption="Отчёт по продажам",
    )


@router.message(Command("etl"))
async def cmd_etl(message: Message) -> None:
    """ETL pipeline status as formatted text."""
    statuses = await run_sync(db.query_etl_status)

    lines = ["<b>ETL Status</b>\n"]
    for s in statuses:
        emoji = "🟢" if s["status"] == "OK" else "🔴"
        lines.append(
            f"  {emoji} {s['pipeline']}: {s['status']} "
            f"({s['rows']:,} rows, {s['duration']})"
        )
    text = "\n".join(lines)

    # split_text handles the case when output is > 4096 chars
    for chunk in split_text(text):
        await message.answer(chunk, parse_mode="HTML")


# ── Main ─────────────────────────────────────────────────────────────

db = FakeOraclePool()


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
        # proxy="http://proxy:8535",
    )
    dp = Dispatcher()

    dp.include_router(router)

    @dp.on_startup
    async def on_startup() -> None:
        me = await bot.get_me()
        # Pass db to scheduler — jobs that accept `db` param get it injected
        scheduler.start(bot, db=db)
        logger.info(
            "Report bot '%s' started, %d scheduled jobs",
            me.nick, len(scheduler.jobs),
        )

    @dp.on_shutdown
    async def on_shutdown() -> None:
        await scheduler.stop()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
