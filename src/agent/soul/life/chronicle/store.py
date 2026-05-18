from __future__ import annotations

import json
from pathlib import Path

from .entry import ChronicleEntry

_FILENAME = "chronicle.jsonl"


class ChronicleStore:
    """Chronicle 的永久追加存储（JSONL）。

    与 ``ExperienceLog`` 不同，Chronicle 不会 purge 旧条目——
    它是 Agent 生命历程的客观事实账本，只增不删。

    查询接口
    --------
    - ``append(entry)``          — 追加一条记录
    - ``recent(n)``              — 最近 n 条（按时间正序）
    - ``by_session(session_id)`` — 按 session 过滤
    - ``all()``                  — 全量（谨慎使用）
    """

    def __init__(self, dir_path: str) -> None:
        self._path = Path(dir_path) / _FILENAME
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: ChronicleEntry) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def recent(self, n: int = 20) -> list[ChronicleEntry]:
        entries = self._load_all()
        return entries[-n:] if len(entries) > n else entries

    def by_session(self, session_id: str) -> list[ChronicleEntry]:
        return [e for e in self._load_all() if e.session_id == session_id]

    def all(self) -> list[ChronicleEntry]:
        return self._load_all()

    def _load_all(self) -> list[ChronicleEntry]:
        if not self._path.exists():
            return []
        entries: list[ChronicleEntry] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(ChronicleEntry.from_dict(json.loads(line)))
        return entries
