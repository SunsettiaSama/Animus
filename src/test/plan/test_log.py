"""Tests for plan.log: PlanLogger.log, read, read_async, rotation."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from plan.config import LogConfig
from plan.log import LogLevel, PlanLogger


@pytest.fixture
def logger(tmp_path):
    cfg = LogConfig(enabled=True, min_level="debug", max_file_size_mb=10.0)
    return PlanLogger(str(tmp_path), "test-plan-id", cfg)


class TestPlanLogger:
    def test_log_and_read(self, logger):
        asyncio.get_event_loop().run_until_complete(logger.info("test_event", task_id="t1"))
        records = logger.read()
        assert len(records) == 1
        assert records[0]["event"] == "test_event"
        assert records[0]["task_id"] == "t1"

    def test_filter_by_level(self, logger):
        asyncio.get_event_loop().run_until_complete(logger.debug("debug_evt"))
        asyncio.get_event_loop().run_until_complete(logger.info("info_evt"))
        asyncio.get_event_loop().run_until_complete(logger.error("error_evt"))
        records = logger.read(level_min=LogLevel.ERROR)
        assert all(r["level"] == "error" for r in records)

    def test_filter_by_task_id(self, logger):
        asyncio.get_event_loop().run_until_complete(logger.info("ev1", task_id="task_a"))
        asyncio.get_event_loop().run_until_complete(logger.info("ev2", task_id="task_b"))
        records = logger.read(task_id="task_a")
        assert all(r["task_id"] == "task_a" for r in records)

    def test_filter_by_event(self, logger):
        asyncio.get_event_loop().run_until_complete(logger.info("special_event"))
        asyncio.get_event_loop().run_until_complete(logger.info("other_event"))
        records = logger.read(event="special_event")
        assert len(records) == 1

    def test_read_async(self, logger):
        asyncio.get_event_loop().run_until_complete(logger.info("async_test"))

        async def _run():
            return await logger.read_async(n=5)

        records = asyncio.get_event_loop().run_until_complete(_run())
        assert any(r["event"] == "async_test" for r in records)

    def test_read_async_tail_n(self, logger):
        async def _run():
            for i in range(10):
                await logger.info(f"evt_{i}")
            return await logger.read_async(n=3)

        records = asyncio.get_event_loop().run_until_complete(_run())
        assert len(records) == 3
        assert records[-1]["event"] == "evt_9"

    def test_disabled_logger_skips(self, tmp_path):
        cfg = LogConfig(enabled=False)
        log = PlanLogger(str(tmp_path), "disabled-plan", cfg)
        asyncio.get_event_loop().run_until_complete(log.info("should_not_log"))
        assert log.read() == []

    def test_level_filtering(self, tmp_path):
        cfg = LogConfig(enabled=True, min_level="warning")
        log = PlanLogger(str(tmp_path), "warn-plan", cfg)
        asyncio.get_event_loop().run_until_complete(log.debug("should_skip"))
        asyncio.get_event_loop().run_until_complete(log.warning("should_appear"))
        records = log.read()
        assert all(r["event"] != "should_skip" for r in records)
        assert any(r["event"] == "should_appear" for r in records)
