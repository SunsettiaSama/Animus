from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .entry import AnchorChronicleEntry, AnchorChronicleKind, ChronicleEntry, ChronicleKind

_FILENAME = "anchor_chronicle.jsonl"


class AnchorChronicleStore:
    """锚点层 Chronicle 永久存储（JSONL）。"""

    def __init__(self, dir_path: str) -> None:
        self._path = Path(dir_path) / _FILENAME
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: AnchorChronicleEntry) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def retract_by_experience_ids(self, experience_ids: set[str]) -> int:
        if not experience_ids or not self._path.exists():
            return 0
        kept: list[str] = []
        removed = 0
        for line in self._path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            d = json.loads(raw)
            if d.get("experience_id", "") in experience_ids:
                removed += 1
                continue
            kept.append(raw)
        if removed:
            with self._path.open("w", encoding="utf-8") as f:
                for row in kept:
                    f.write(row + "\n")
        return removed

    def recent(self, n: int = 20) -> list[AnchorChronicleEntry]:
        entries = self._load_all()
        return entries[-n:] if len(entries) > n else entries

    def recent_days(self, days: int) -> list[AnchorChronicleEntry]:
        if days <= 0:
            return self._load_all()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out: list[AnchorChronicleEntry] = []
        for e in self._load_all():
            ts = e.ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                out.append(e)
        return out

    def count_kind(self, kind: AnchorChronicleKind, days: int) -> int:
        return sum(1 for e in self.recent_days(days) if e.kind == kind)

    def format_dialogue_digest(self, days: int = 1) -> str:
        turns = [
            e for e in self.recent_days(days)
            if e.kind == AnchorChronicleKind.user_turn
        ]
        if not turns:
            return ""
        return "\n".join(f"- {e.summary}" for e in turns[-15:])

    def _load_all(self) -> list[AnchorChronicleEntry]:
        if not self._path.exists():
            return []
        entries: list[AnchorChronicleEntry] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(AnchorChronicleEntry.from_dict(json.loads(line)))
        return entries


ChronicleStore = AnchorChronicleStore
