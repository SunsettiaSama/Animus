from __future__ import annotations

import json
from pathlib import Path

from react.persona.chronicle import PersonaChronicle
from react.persona.profile import PersonaProfile


class PersonaStore:
    def __init__(self, persona_dir: str = ".react/persona") -> None:
        self._dir = Path(persona_dir)
        self._profile_path = self._dir / "profile.json"
        self._chronicle_path = self._dir / "chronicle.json"

    def load_profile(self) -> PersonaProfile:
        if not self._profile_path.exists():
            default = PersonaProfile()
            self.save_profile(default)
            return default
        with open(self._profile_path, encoding="utf-8") as f:
            return PersonaProfile.from_dict(json.load(f))

    def save_profile(self, profile: PersonaProfile) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._profile_path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)

    def load_chronicle(self, max_entries: int = 100, max_entry_chars: int = 0) -> PersonaChronicle:
        if not self._chronicle_path.exists():
            return PersonaChronicle(max_entries=max_entries, max_entry_chars=max_entry_chars)
        with open(self._chronicle_path, encoding="utf-8") as f:
            return PersonaChronicle.from_dict(json.load(f), max_entries=max_entries, max_entry_chars=max_entry_chars)

    def save_chronicle(self, chronicle: PersonaChronicle) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._chronicle_path, "w", encoding="utf-8") as f:
            json.dump(chronicle.to_dict(), f, ensure_ascii=False, indent=2)
