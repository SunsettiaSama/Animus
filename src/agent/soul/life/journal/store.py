from __future__ import annotations

import json
from pathlib import Path

from .journal import LifeJournal

_FILENAME = "journal.json"


class JournalStore:
    """LifeJournal 的 JSON 文件持久化。"""

    def __init__(self, dir_path: str) -> None:
        self._path = Path(dir_path) / _FILENAME
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> LifeJournal:
        if not self._path.exists():
            return LifeJournal()
        return LifeJournal.from_dict(json.loads(self._path.read_text(encoding="utf-8")))

    def save(self, journal: LifeJournal) -> None:
        self._path.write_text(
            json.dumps(journal.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
