from __future__ import annotations

import json
from pathlib import Path

from .schema import PersonaDistillPack

_DISTILL_FILENAME = "persona_distill.json"


class PersonaDistillStore:
    def __init__(self, persona_dir: str) -> None:
        self._path = Path(persona_dir) / _DISTILL_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> PersonaDistillPack | None:
        if not self._path.is_file():
            return None
        text = self._path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"persona_distill.json 根节点须为 object: {self._path}")
        return PersonaDistillPack.from_dict(data)

    def save(self, pack: PersonaDistillPack) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(pack.to_dict(), ensure_ascii=False, indent=2)
        self._path.write_text(payload + "\n", encoding="utf-8")

    def clear(self) -> None:
        if self._path.is_file():
            self._path.unlink()
