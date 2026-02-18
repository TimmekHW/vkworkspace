"""Run synchronous code in async handlers without blocking the event loop.

Most database drivers (cx_Oracle, psycopg2), pandas, openpyxl, and
other heavy libraries are synchronous. Calling them directly in an
async handler blocks the entire bot. These utilities solve that.

Function wrapper::

    from vkworkspace.utils.sync import run_sync

    @router.message(Command("report"))
    async def cmd_report(message: Message):
        # Oracle query runs in a thread — event loop stays free
        data = await run_sync(pd.read_sql, "SELECT * FROM sales", conn)
        await message.answer(format_report(data))

Decorator::

    from vkworkspace.utils.sync import sync_to_async

    @sync_to_async
    def fetch_sales(conn, month: str) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM sales WHERE month = :m", conn, params={"m": month})

    @router.message(Command("sales"))
    async def cmd_sales(message: Message):
        df = await fetch_sales(oracle_conn, "2024-01")
        await message.answer(str(df))
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous function in a thread pool.

    Wraps ``asyncio.to_thread`` — runs *func* in a separate thread
    so the event loop is not blocked.

    Args:
        func: Synchronous function to call.
        *args: Positional arguments for *func*.
        **kwargs: Keyword arguments for *func*.

    Returns:
        The return value of *func*.

    Example::

        import pandas as pd

        # In an async handler:
        df = await run_sync(pd.read_sql, "SELECT * FROM kpi", oracle_conn)

        # Heavy computation:
        result = await run_sync(generate_excel_report, data, output_path="/tmp/report.xlsx")

        # cx_Oracle:
        rows = await run_sync(cursor.execute, "SELECT * FROM departments")
    """
    return await asyncio.to_thread(func, *args, **kwargs)


def sync_to_async(func: Callable[..., T]) -> Callable[..., Awaitable[T]]:
    """Decorator: turn a sync function into an async one.

    The decorated function runs in a thread pool via ``asyncio.to_thread``.

    Example::

        @sync_to_async
        def query_oracle(sql: str) -> list[dict]:
            with cx_Oracle.connect(DSN) as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

        # Now it's async:
        rows = await query_oracle("SELECT * FROM departments")

        @sync_to_async
        def build_excel(data: list[dict]) -> bytes:
            import openpyxl
            wb = openpyxl.Workbook()
            # ... fill workbook ...
            from io import BytesIO
            buf = BytesIO()
            wb.save(buf)
            return buf.getvalue()

        excel = await build_excel(sales_data)
        await message.answer_file(file=InputFile(excel, filename="report.xlsx"))
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper
