from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone

from runtime.scheduler.event import TimelineEvent

_TIMELINE_TOOL_NAMES = frozenset({"delegate_task"})


class TimelineStore:
    def __init__(self, directory: str) -> None:
        self._dir = directory

    def _today_path(self) -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self._dir, f"{date_str}.jsonl")

    def append(self, type: str, payload: dict) -> None:
        os.makedirs(self._dir, exist_ok=True)
        event = TimelineEvent.now(type, payload)
        with open(self._today_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def read(self, date: str | None = None) -> list[dict]:
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(self._dir, f"{date}.jsonl")
        if not os.path.exists(path):
            return []
        events = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def make_tool_sink(
        self,
        filter_names: frozenset[str] | None = None,
    ) -> Callable[[str, dict, str], None]:
        watched = filter_names if filter_names is not None else _TIMELINE_TOOL_NAMES

        def _sink(action_name: str, args: dict, result: str) -> None:
            if action_name not in watched:
                return
            self.append("tool_call", {
                "action": action_name,
                "args": args,
                "result": result[:500] if len(result) > 500 else result,
            })

        return _sink
