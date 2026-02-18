"""Tests for Scheduler — interval, daily, weekly jobs."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from vkworkspace.utils.scheduler import (
    Scheduler,
    _seconds_until,
    _seconds_until_weekday,
)


class TestSecondsUntil:
    def test_future_today(self):
        fake_now = datetime(2026, 1, 1, 8, 0, 0)
        with patch("vkworkspace.utils.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _seconds_until(9, 0)
        assert result == pytest.approx(3600.0)

    def test_past_today_goes_to_tomorrow(self):
        fake_now = datetime(2026, 1, 1, 10, 0, 0)
        with patch("vkworkspace.utils.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _seconds_until(9, 0)
        # 23 hours
        assert result == pytest.approx(23 * 3600.0)


class TestSecondsUntilWeekday:
    def test_future_same_day(self):
        # Wednesday 2026-01-07 08:00, target Wednesday 09:00
        fake_now = datetime(2026, 1, 7, 8, 0, 0)
        assert fake_now.weekday() == 2  # Wednesday
        with patch("vkworkspace.utils.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _seconds_until_weekday(2, 9, 0)
        assert result == pytest.approx(3600.0)

    def test_past_same_day_goes_to_next_week(self):
        # Wednesday 2026-01-07 10:00, target Wednesday 09:00
        fake_now = datetime(2026, 1, 7, 10, 0, 0)
        with patch("vkworkspace.utils.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _seconds_until_weekday(2, 9, 0)
        # 6 days 23 hours
        assert result == pytest.approx(6 * 86400 + 23 * 3600)

    def test_future_different_day(self):
        # Monday 2026-01-05 12:00, target Friday 18:00
        fake_now = datetime(2026, 1, 5, 12, 0, 0)
        assert fake_now.weekday() == 0  # Monday
        with patch("vkworkspace.utils.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _seconds_until_weekday(4, 18, 0)
        # 4 days 6 hours
        assert result == pytest.approx(4 * 86400 + 6 * 3600)


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_interval_job_runs(self):
        scheduler = Scheduler()
        calls: list[str] = []

        @scheduler.interval(seconds=0.05, name="tick")
        async def tick(bot):
            calls.append("tick")

        bot = AsyncMock()
        scheduler.start(bot)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert len(calls) >= 2

    @pytest.mark.asyncio
    async def test_interval_run_at_start_false(self):
        scheduler = Scheduler()
        calls: list[str] = []

        @scheduler.interval(seconds=60, run_at_start=False, name="lazy")
        async def lazy(bot):
            calls.append("lazy")

        bot = AsyncMock()
        scheduler.start(bot)
        await asyncio.sleep(0.1)
        await scheduler.stop()

        # Should not have run (interval=60s, run_at_start=False)
        assert len(calls) == 0

    @pytest.mark.asyncio
    async def test_double_start_ignored(self):
        scheduler = Scheduler()

        @scheduler.interval(seconds=0.05)
        async def tick(bot):
            pass

        bot = AsyncMock()
        scheduler.start(bot)
        initial_tasks = len(scheduler._tasks)
        scheduler.start(bot)  # second start — should be ignored
        assert len(scheduler._tasks) == initial_tasks
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        scheduler = Scheduler()

        @scheduler.interval(seconds=0.05)
        async def tick(bot):
            pass

        bot = AsyncMock()
        scheduler.start(bot)
        assert scheduler.is_running is True
        await scheduler.stop()
        assert scheduler.is_running is False
        assert len(scheduler._tasks) == 0

    @pytest.mark.asyncio
    async def test_job_exception_does_not_crash_scheduler(self):
        scheduler = Scheduler()
        calls = []

        @scheduler.interval(seconds=0.05, name="boom")
        async def boom(bot):
            calls.append("boom")
            raise RuntimeError("test error")

        bot = AsyncMock()
        scheduler.start(bot)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # Should have retried despite exceptions
        assert len(calls) >= 2

    @pytest.mark.asyncio
    async def test_jobs_property(self):
        scheduler = Scheduler()

        @scheduler.interval(seconds=1, name="a")
        async def a(bot):
            pass

        @scheduler.daily(hour=9, name="b")
        async def b(bot):
            pass

        assert scheduler.jobs == ["a", "b"]


class TestSchedulerDI:
    @pytest.mark.asyncio
    async def test_extra_kwargs_injected(self):
        scheduler = Scheduler()
        received: list[dict] = []

        @scheduler.interval(seconds=0.05)
        async def job(bot, db):
            received.append({"bot": bot, "db": db})

        bot = AsyncMock()
        fake_db = object()
        scheduler.start(bot, db=fake_db, config="not_needed")
        await asyncio.sleep(0.1)
        await scheduler.stop()

        assert len(received) >= 1
        assert received[0]["bot"] is bot
        assert received[0]["db"] is fake_db

    @pytest.mark.asyncio
    async def test_var_kwargs_receives_all(self):
        scheduler = Scheduler()
        received: list[dict] = []

        @scheduler.interval(seconds=0.05)
        async def job(bot, **kwargs):
            received.append(kwargs)

        bot = AsyncMock()
        scheduler.start(bot, db="db_val", config="cfg_val")
        await asyncio.sleep(0.1)
        await scheduler.stop()

        assert len(received) >= 1
        assert received[0] == {"db": "db_val", "config": "cfg_val"}

    @pytest.mark.asyncio
    async def test_no_extra_kwargs_filtered(self):
        scheduler = Scheduler()
        received: list[str] = []

        @scheduler.interval(seconds=0.05)
        async def job(bot):
            received.append("ok")

        bot = AsyncMock()
        # Extra kwargs should be silently filtered out
        scheduler.start(bot, db="unused", config="unused")
        await asyncio.sleep(0.1)
        await scheduler.stop()

        assert len(received) >= 1
