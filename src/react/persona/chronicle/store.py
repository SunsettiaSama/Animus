from __future__ import annotations

import json
from pathlib import Path

from react.persona.chronicle.chronicle import PersonaChronicle


class ChronicleStore:
    """事件子模块的持久化层（chronicle.json）。"""

    def __init__(self, persona_dir: str) -> None:
        self._dir = Path(persona_dir)
        self._chronicle_path = self._dir / "chronicle.json"

    def load_chronicle(
        self, max_entries: int = 100, max_entry_chars: int = 0
    ) -> PersonaChronicle:
        if not self._chronicle_path.exists():
            return PersonaChronicle(max_entries=max_entries, max_entry_chars=max_entry_chars)
        with open(self._chronicle_path, encoding="utf-8") as f:
            return PersonaChronicle.from_dict(
                json.load(f), max_entries=max_entries, max_entry_chars=max_entry_chars
            )

    def save_chronicle(self, chronicle: PersonaChronicle) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._chronicle_path, "w", encoding="utf-8") as f:
            json.dump(chronicle.to_dict(), f, ensure_ascii=False, indent=2)
