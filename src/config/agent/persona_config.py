from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersonaConfig:
    enabled: bool = False
    persona_dir: str = ""
    max_profile_chars: int = 500
    evolution_enabled: bool = False
    evolve_interval: int = 1
    skills_enabled: bool = True
    max_skills: int = 50
    max_skills_in_prompt: int = 5
    max_skills_chars: int = 600
    reflection_enabled: bool = False
    reflect_interval: int = 3
    max_reflection_chars: int = 400
    preference_enabled: bool = True
    preference_window_days: int = 30
    max_preference_topics: int = 10
    max_preference_chars: int = 400
    preference_update_every_n: int = 3

    @classmethod
    def from_dict(cls, d: dict, persona_dir: str = "") -> PersonaConfig:
        return cls(
            enabled=bool(d.get("enabled", False)),
            persona_dir=d.get("persona_dir", persona_dir),
            max_profile_chars=int(d.get("max_profile_chars", 500)),
            evolution_enabled=bool(d.get("evolution_enabled", False)),
            evolve_interval=int(d.get("evolve_interval", 1)),
            skills_enabled=bool(d.get("skills_enabled", True)),
            max_skills=int(d.get("max_skills", 50)),
            max_skills_in_prompt=int(d.get("max_skills_in_prompt", 5)),
            max_skills_chars=int(d.get("max_skills_chars", 600)),
            reflection_enabled=bool(d.get("reflection_enabled", False)),
            reflect_interval=int(d.get("reflect_interval", 3)),
            max_reflection_chars=int(d.get("max_reflection_chars", 400)),
            preference_enabled=bool(d.get("preference_enabled", True)),
            preference_window_days=int(d.get("preference_window_days", 30)),
            max_preference_topics=int(d.get("max_preference_topics", 10)),
            max_preference_chars=int(d.get("max_preference_chars", 400)),
            preference_update_every_n=int(d.get("preference_update_every_n", 3)),
        )
