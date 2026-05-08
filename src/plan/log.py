from __future__ import annotations

import asyncio
import json
import os
import time
import traceback as tb
from enum import IntEnum
from pathlib import Path
from typing import Any

try:
    import aiofiles
    _AIOFILES = True
except ImportError:
    _AIOFILES = False

from plan.config import LogConfig
from typing import Callable


class LogLevel(IntEnum):
    DEBUG    = 10
    INFO     = 20
    WARNING  = 30
    ERROR    = 40
    CRITICAL = 50


_LEVEL_NAMES = {v: k for k, v in LogLevel.__members__.items()}


class PlanLogger:
    def __init__(self, plan_dir: str, plan_id: str, cfg: LogConfig) -> None:
        self._plan_id = plan_id
        self._cfg = cfg
        log_dir = Path(plan_dir) / plan_id
        log_dir.mkdir(parents=True, exist_ok=True)
        self._path = log_dir / "plan.log.jsonl"
        try:
            self._min_level = LogLevel[cfg.min_level.upper()]
        except KeyError:
            self._min_level = LogLevel.DEBUG
        self._lock = asyncio.Lock()
        self._line_sink: Callable[[dict], None] | None = None

    def set_line_sink(self, sink: Callable[[dict], None] | None) -> None:
        """Register a callback that receives each log record for real-time SSE push."""
        self._line_sink = sink

    # ── Core write ────────────────────────────────────────────────────────────

    async def log(self, level: LogLevel, event: str, **payload: Any) -> None:
        if not self._cfg.enabled or level < self._min_level:
            return
        record = {
            "ts": time.time(),
            "level": _LEVEL_NAMES.get(level, "unknown").lower(),
            "event": event,
            "plan_id": self._plan_id,
            **payload,
        }
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        async with self._lock:
            if _AIOFILES:
                import aiofiles  # type: ignore
                async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
                    await f.write(line)
            else:
                self._path.open("a", encoding="utf-8").write(line)

        # Push to SSE stream if a sink is registered
        if self._line_sink is not None:
            self._line_sink({"type": "log_line", "plan_id": self._plan_id, **record})

        # Simple size-based rotation
        self._maybe_rotate()

    def _maybe_rotate(self) -> None:
        max_bytes = int(self._cfg.max_file_size_mb * 1024 * 1024)
        if self._path.exists() and self._path.stat().st_size > max_bytes:
            rotated = self._path.with_suffix(
                f".{int(time.time())}.jsonl"
            )
            self._path.rename(rotated)

    # ── Convenience methods ───────────────────────────────────────────────────

    async def debug(self, event: str, **kw: Any) -> None:
        await self.log(LogLevel.DEBUG, event, **kw)

    async def info(self, event: str, **kw: Any) -> None:
        await self.log(LogLevel.INFO, event, **kw)

    async def warning(self, event: str, **kw: Any) -> None:
        await self.log(LogLevel.WARNING, event, **kw)

    async def error(self, event: str, *, exc: Exception | None = None, **kw: Any) -> None:
        if exc is not None:
            kw["traceback"] = tb.format_exc()
            kw["error_type"] = type(exc).__name__
            kw["error_msg"] = str(exc)
        await self.log(LogLevel.ERROR, event, **kw)

    async def critical(self, event: str, *, exc: Exception | None = None, **kw: Any) -> None:
        if exc is not None:
            kw["traceback"] = tb.format_exc()
            kw["error_type"] = type(exc).__name__
            kw["error_msg"] = str(exc)
        await self.log(LogLevel.CRITICAL, event, **kw)

    # ── Read / query ──────────────────────────────────────────────────────────

    def read(
        self,
        level_min: LogLevel = LogLevel.DEBUG,
        event: str | None = None,
        task_id: str | None = None,
    ) -> list[dict]:
        if not self._path.exists():
            return []
        results: list[dict] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                lvl_name = record.get("level", "debug").upper()
                lvl = LogLevel.__members__.get(lvl_name, LogLevel.DEBUG)
                if lvl < level_min:
                    continue
                if event and record.get("event") != event:
                    continue
                if task_id and record.get("task_id") != task_id:
                    continue
                results.append(record)
        return results

    async def read_async(
        self,
        level_min: LogLevel = LogLevel.DEBUG,
        event: str | None = None,
        task_id: str | None = None,
        n: int | None = None,
    ) -> list[dict]:
        import functools
        loop = asyncio.get_event_loop()
        fn = functools.partial(self.read, level_min=level_min, event=event, task_id=task_id)
        records = await loop.run_in_executor(None, fn)
        if n is not None:
            records = records[-n:]
        return records
