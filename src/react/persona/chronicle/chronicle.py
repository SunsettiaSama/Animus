from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ChronicleEntry:
    timestamp: str
    narrative: str


class PersonaChronicle:
    def __init__(self, max_entries: int = 100, max_entry_chars: int = 0) -> None:
        self._max = max_entries
        self._max_entry_chars = max_entry_chars
        self._entries: list[ChronicleEntry] = []

    def append(self, narrative: str) -> None:
        if self._max_entry_chars > 0 and len(narrative) > self._max_entry_chars:
            return
        entry = ChronicleEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            narrative=narrative,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max :]

    def render(self, recent: int = 5) -> str:
        entries = self._entries[-recent:] if self._entries else []
        if not entries:
            return ""
        return "\n\n".join(f"[{e.timestamp[:10]}] {e.narrative}" for e in entries)

    def __len__(self) -> int:
        return len(self._entries)

    def to_dict(self) -> dict:
        return {
            "entries": [
                {"timestamp": e.timestamp, "narrative": e.narrative}
                for e in self._entries
            ]
        }

    @classmethod
    def from_dict(
        cls, d: dict, max_entries: int = 100, max_entry_chars: int = 0
    ) -> PersonaChronicle:
        chronicle = cls(max_entries=max_entries, max_entry_chars=max_entry_chars)
        chronicle._entries = [
            ChronicleEntry(timestamp=e["timestamp"], narrative=e["narrative"])
            for e in d.get("entries", [])
        ]
        return chronicle
