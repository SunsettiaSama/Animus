from __future__ import annotations

from collections.abc import Callable

from runtime.scheduler.timeline import TimelineStore


class TimelineService:
    """时间轴门面：仅封装按日 JSONL 事件日志的读写与工具层 sink，不承担调度、心跳或其它业务。"""

    def __init__(self, directory: str) -> None:
        self._directory = directory
        self._store = TimelineStore(directory)

    @property
    def directory(self) -> str:
        return self._directory

    def append(self, type: str, payload: dict) -> None:
        self._store.append(type, payload)

    def read(self, date: str | None = None) -> list[dict]:
        return self._store.read(date)

    def make_tool_sink(
        self,
        filter_names: frozenset[str] | None = None,
    ) -> Callable[[str, dict, str], None]:
        return self._store.make_tool_sink(filter_names)
