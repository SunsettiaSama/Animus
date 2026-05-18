from __future__ import annotations

import json
from pathlib import Path

from .event import SurpriseEvent

_FILENAME = "surprise_events.jsonl"


class SurpriseStore:
    """意外事件的永久追加存储（JSONL）。

    与 ``ChronicleStore`` 相同策略：只增不删，完整保存每一次意外的发生。
    """

    def __init__(self, dir_path: str) -> None:
        self._path = Path(dir_path) / _FILENAME
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: SurpriseEvent) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def recent(self, n: int = 10) -> list[SurpriseEvent]:
        events = self._load_all()
        return events[-n:] if len(events) > n else events

    def all(self) -> list[SurpriseEvent]:
        return self._load_all()

    def _load_all(self) -> list[SurpriseEvent]:
        if not self._path.exists():
            return []
        events: list[SurpriseEvent] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(SurpriseEvent.from_dict(json.loads(line)))
        return events
