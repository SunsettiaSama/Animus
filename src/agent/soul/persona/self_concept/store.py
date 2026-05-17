from __future__ import annotations

import json
from pathlib import Path

from .concept import SelfConcept

_FILENAME = "self_concept.json"


class SelfConceptStore:
    def __init__(self, persona_dir: str) -> None:
        self._path = Path(persona_dir) / _FILENAME

    def load(self) -> SelfConcept:
        if not self._path.exists():
            return SelfConcept()
        with open(self._path, encoding="utf-8") as f:
            return SelfConcept.from_dict(json.load(f))

    def save(self, concept: SelfConcept) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(concept.to_dict(), f, ensure_ascii=False, indent=2)

    def exists(self) -> bool:
        return self._path.exists()

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
