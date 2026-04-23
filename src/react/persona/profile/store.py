from __future__ import annotations

import json
from pathlib import Path

from react.persona.profile.profile import PersonaProfile
from react.persona.profile.skills import SkillsLibrary


class ProfileStore:
    """人格子模块的持久化层（profile.json / skills.json / reflection.txt）。"""

    def __init__(self, persona_dir: str) -> None:
        self._dir = Path(persona_dir)
        self._profile_path    = self._dir / "profile.json"
        self._skills_path     = self._dir / "skills.json"
        self._reflection_path = self._dir / "reflection.txt"

    # ── Profile ───────────────────────────────────────────────────────────────

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

    # ── Skills ────────────────────────────────────────────────────────────────

    def load_skills(self, max_skills: int = 20) -> SkillsLibrary:
        if not self._skills_path.exists():
            return SkillsLibrary(max_skills=max_skills)
        with open(self._skills_path, encoding="utf-8") as f:
            return SkillsLibrary.from_dict(json.load(f), max_skills=max_skills)

    def save_skills(self, skills: SkillsLibrary) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._skills_path, "w", encoding="utf-8") as f:
            json.dump(skills.to_dict(), f, ensure_ascii=False, indent=2)

    # ── Reflection ────────────────────────────────────────────────────────────

    def load_reflection(self) -> str:
        if not self._reflection_path.exists():
            return ""
        return self._reflection_path.read_text(encoding="utf-8").strip()

    def save_reflection(self, text: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._reflection_path.write_text(text.strip(), encoding="utf-8")
