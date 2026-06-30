from __future__ import annotations

import json
from pathlib import Path

from .item import LandmarkAgenda

_FILENAME = "landmark_agendas.json"


class LandmarkAgendaStore:
    def __init__(self, life_dir: str) -> None:
        self._path = Path(life_dir) / _FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[LandmarkAgenda]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"invalid landmark agenda store: {self._path}")
        return [LandmarkAgenda.from_dict(item) for item in raw if isinstance(item, dict)]

    def save(self, agendas: list[LandmarkAgenda]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.to_dict() for item in agendas]
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append(self, agenda: LandmarkAgenda) -> None:
        items = self.load()
        items.append(agenda)
        self.save(items)

    def latest(self, *, limit: int = 10) -> list[LandmarkAgenda]:
        items = self.load()
        if limit <= 0:
            return []
        return items[-limit:]

    def get(self, agenda_id: str) -> LandmarkAgenda | None:
        token = agenda_id.strip()
        if not token:
            return None
        for item in self.load():
            if item.id == token:
                return item
        return None

    def upsert(self, agenda: LandmarkAgenda) -> None:
        items = self.load()
        replaced = False
        for idx, item in enumerate(items):
            if item.id == agenda.id:
                items[idx] = agenda
                replaced = True
                break
        if not replaced:
            items.append(agenda)
        self.save(items)
