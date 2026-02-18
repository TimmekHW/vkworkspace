"""Lightweight async task scheduler — zero dependencies, pure asyncio.

Schedule periodic tasks for your bot: health checks, reports, alerts.
No APScheduler needed.

Usage::

    from vkworkspace.utils.scheduler import Scheduler

    scheduler = Scheduler()

    @scheduler.interval(seconds=300)
    async def check_cpu(bot):
        cpu = await get_cpu_usage()
        if cpu > 90:
            await bot.send_text(ONCALL_CHAT, f"CPU: {cpu}%")

    @scheduler.daily(hour=9, minute=0)
    async def morning_report(bot):
        await bot.send_text(TEAM_CHAT, build_report())

    @scheduler.weekly(weekday=4, hour=18)  # Friday 18:00
    async def weekly_summary(bot):
        await bot.send_text(TEAM_CHAT, build_weekly())

    # Start in on_startup hook — pass extra dependencies:
    @dp.on_startup
    async def setup():
        scheduler.start(bot, db=oracle_pool, config=app_config)
        # Jobs receive only kwargs matching their signature.
        # check_cpu(bot) gets bot only.
        # morning_report(bot) gets bot only.
        # A job with def report(bot, db): gets bot + db.

    # Stop in on_shutdown hook (optional — tasks cancel on process exit):
    @dp.on_shutdown
    async def teardown():
        await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

SchedulerFunc = Callable[..., Awaitable[Any]]


class _Job(ABC):
    """Base class for scheduled jobs."""

    def __init__(self, func: SchedulerFunc, name: str | None = None) -> None:
        self.func = func
        self.name = name or func.__name__
        # Inspect signature for DI-style kwarg filtering
        sig = inspect.signature(func)
        self._params: set[str] = set()
        self._has_kwargs = False
        for param_name, param in sig.parameters.items():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                self._has_kwargs = True
            else:
                self._params.add(param_name)

    async def _call(self, bot: Any, extra: dict[str, Any]) -> None:
        """Call the job function with signature-filtered kwargs."""
        if self._has_kwargs:
            await self.func(bot, **extra)
        else:
            filtered = {k: v for k, v in extra.items() if k in self._params}
            await self.func(bot, **filtered)

    @abstractmethod
    async def run(
        self, bot: Any, is_running: Callable[[], bool], extra: dict[str, Any],
    ) -> None:
        """Run the job loop until is_running() returns False."""


class _IntervalJob(_Job):
    """Run a function every N seconds."""

    def __init__(
        self,
        func: SchedulerFunc,
        seconds: float,
        run_at_start: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(func, name)
        self.seconds = seconds
        self.run_at_start = run_at_start

    async def run(
        self, bot: Any, is_running: Callable[[], bool], extra: dict[str, Any],
    ) -> None:
        if not self.run_at_start:
            await _interruptible_sleep(self.seconds, is_running)

        while is_running():
            try:
                await self._call(bot, extra)
            except Exception:
                logger.exception("Scheduler job '%s' failed", self.name)
            await _interruptible_sleep(self.seconds, is_running)


class _DailyJob(_Job):
    """Run a function daily at a specific time."""

    def __init__(
        self,
        func: SchedulerFunc,
        hour: int,
        minute: int,
        name: str | None = None,
    ) -> None:
        super().__init__(func, name)
        self.hour = hour
        self.minute = minute

    async def run(
        self, bot: Any, is_running: Callable[[], bool], extra: dict[str, Any],
    ) -> None:
        while is_running():
            wait = _seconds_until(self.hour, self.minute)
            await _interruptible_sleep(wait, is_running)

            if not is_running():
                break

            try:
                await self._call(bot, extra)
            except Exception:
                logger.exception("Scheduler job '%s' failed", self.name)

            # Sleep 61s to avoid double-firing within the same minute
            await _interruptible_sleep(61, is_running)


class _WeeklyJob(_Job):
    """Run a function weekly on a specific weekday at a specific time."""

    def __init__(
        self,
        func: SchedulerFunc,
        weekday: int,
        hour: int,
        minute: int,
        name: str | None = None,
    ) -> None:
        super().__init__(func, name)
        self.weekday = weekday  # 0=Monday, 6=Sunday
        self.hour = hour
        self.minute = minute

    async def run(
        self, bot: Any, is_running: Callable[[], bool], extra: dict[str, Any],
    ) -> None:
        while is_running():
            wait = _seconds_until_weekday(self.weekday, self.hour, self.minute)
            await _interruptible_sleep(wait, is_running)

            if not is_running():
                break

            try:
                await self._call(bot, extra)
            except Exception:
                logger.exception("Scheduler job '%s' failed", self.name)

            # Sleep 61s to avoid double-firing
            await _interruptible_sleep(61, is_running)


class Scheduler:
    """Lightweight async task scheduler for bot periodic tasks.

    Zero dependencies — uses only ``asyncio`` and ``datetime``.

    Register jobs with decorators, then call :meth:`start` in your
    ``on_startup`` hook. Jobs receive the ``bot`` instance as first argument.

    Example::

        scheduler = Scheduler()

        @scheduler.interval(seconds=60)
        async def ping(bot):
            await bot.send_text("admin@corp.ru", "I'm alive!")

        @scheduler.daily(hour=9, minute=0)
        async def report(bot):
            await bot.send_text("team@chat.corp.ru", "Good morning!")

        @dp.on_startup
        async def setup():
            scheduler.start(bot)
    """

    def __init__(self) -> None:
        self._jobs: list[_Job] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

    # ── decorators ────────────────────────────────────────────────────

    def interval(
        self,
        seconds: float,
        run_at_start: bool = True,
        name: str | None = None,
    ) -> Callable[[SchedulerFunc], SchedulerFunc]:
        """Run a function every *seconds*.

        Args:
            seconds: Interval in seconds between runs.
            run_at_start: Execute immediately on start (default ``True``).
                Set ``False`` to wait one interval before first run.
            name: Job name for logging (default: function name).

        Example::

            @scheduler.interval(seconds=300)
            async def check_cpu(bot):
                ...
        """
        def decorator(func: SchedulerFunc) -> SchedulerFunc:
            self._jobs.append(_IntervalJob(func, seconds, run_at_start, name))
            return func
        return decorator

    def daily(
        self,
        hour: int = 0,
        minute: int = 0,
        name: str | None = None,
    ) -> Callable[[SchedulerFunc], SchedulerFunc]:
        """Run a function daily at *hour*:*minute* (local time).

        Args:
            hour: Hour (0–23).
            minute: Minute (0–59).
            name: Job name for logging.

        Example::

            @scheduler.daily(hour=9, minute=0)
            async def morning_report(bot):
                ...
        """
        def decorator(func: SchedulerFunc) -> SchedulerFunc:
            self._jobs.append(_DailyJob(func, hour, minute, name))
            return func
        return decorator

    def weekly(
        self,
        weekday: int = 0,
        hour: int = 0,
        minute: int = 0,
        name: str | None = None,
    ) -> Callable[[SchedulerFunc], SchedulerFunc]:
        """Run a function weekly on *weekday* at *hour*:*minute*.

        Args:
            weekday: Day of week (0=Monday, 6=Sunday).
            hour: Hour (0–23).
            minute: Minute (0–59).
            name: Job name for logging.

        Example::

            @scheduler.weekly(weekday=4, hour=18)
            async def friday_summary(bot):
                ...
        """
        def decorator(func: SchedulerFunc) -> SchedulerFunc:
            self._jobs.append(_WeeklyJob(func, weekday, hour, minute, name))
            return func
        return decorator

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self, bot: Any, **kwargs: Any) -> None:
        """Start all scheduled jobs as background tasks.

        Extra keyword arguments are injected into job functions by
        parameter name (like middleware data in handlers).

        Args:
            bot: Bot instance (always passed as first argument).
            **kwargs: Extra dependencies (db, config, redis, etc.).
                Only kwargs matching the job function's parameter names
                are passed. Functions with ``**kwargs`` receive all.

        Example::

            @dp.on_startup
            async def setup():
                scheduler.start(bot, db=oracle_pool, config=app_config)

            @scheduler.interval(seconds=300)
            async def check_etl(bot, db):
                # db is injected, config is not (not in signature)
                ...

            @scheduler.daily(hour=9)
            async def report(bot, db, config):
                # both db and config are injected
                ...
        """
        if self._running:
            logger.warning("Scheduler is already running")
            return
        self._running = True
        for job in self._jobs:
            task = asyncio.create_task(
                job.run(bot, lambda: self._running, kwargs),
                name=f"scheduler:{job.name}",
            )
            self._tasks.append(task)
        logger.info(
            "Scheduler started: %s",
            ", ".join(j.name for j in self._jobs) or "(no jobs)",
        )

    async def stop(self) -> None:
        """Stop all scheduled jobs and wait for them to finish.

        Call this in your ``on_shutdown`` hook::

            @dp.on_shutdown
            async def teardown():
                await scheduler.stop()
        """
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        """Whether the scheduler is currently running."""
        return self._running

    @property
    def jobs(self) -> list[str]:
        """List of registered job names."""
        return [j.name for j in self._jobs]


# ── helpers ──────────────────────────────────────────────────────────

async def _interruptible_sleep(
    seconds: float,
    is_running: Callable[[], bool],
    chunk: float = 5.0,
) -> None:
    """Sleep in small chunks so we can check is_running() and exit fast."""
    remaining = seconds
    while remaining > 0 and is_running():
        await asyncio.sleep(min(chunk, remaining))
        remaining -= chunk


def _seconds_until(hour: int, minute: int) -> float:
    """Seconds from now until next occurrence of hour:minute today/tomorrow."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _seconds_until_weekday(weekday: int, hour: int, minute: int) -> float:
    """Seconds from now until next occurrence of weekday at hour:minute."""
    now = datetime.now()
    days_ahead = weekday - now.weekday()
    if days_ahead < 0:
        days_ahead += 7
    target = now.replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    ) + timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(weeks=1)
    return (target - now).total_seconds()
