from __future__ import annotations

import json
from pathlib import Path

from ...persona.profile.profile import PersonaProfile


class ProfileStore:
    """静态人格画像的持久化层（profile.json）。

    只读写原始用户输入，不持有 skills / reflection 等演化数据。
    演化数据由各自子模块（SelfConceptStore、EmotionalStateStore 等）负责。
    """

    def __init__(self, persona_dir: str) -> None:
        self._dir = Path(persona_dir)
        self._profile_path = self._dir / "profile.json"

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
