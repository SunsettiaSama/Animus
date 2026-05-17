from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str
    description: str
    trigger: str = ""
    priority: int = 5


class SkillsLibrary:
    """可演化的行为技能库。技能按优先级排序，超出 max_skills 时自动淘汰低优先级项。"""

    def __init__(self, max_skills: int = 20) -> None:
        self._max = max_skills
        self._skills: list[Skill] = []

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills)

    def __len__(self) -> int:
        return len(self._skills)

    def add(self, skill: Skill) -> None:
        self._skills = [s for s in self._skills if s.name != skill.name]
        self._skills.append(skill)
        if len(self._skills) > self._max:
            self._skills.sort(key=lambda s: s.priority, reverse=True)
            self._skills = self._skills[: self._max]

    def remove(self, name: str) -> None:
        self._skills = [s for s in self._skills if s.name != name]

    def update_skill(self, name: str, **kwargs: object) -> None:
        for s in self._skills:
            if s.name == name:
                for k, v in kwargs.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                return

    def render(self, top_k: int = 5) -> str:
        top = sorted(self._skills, key=lambda s: s.priority, reverse=True)[:top_k]
        if not top:
            return ""
        lines = ["【行为技能库】"]
        for s in top:
            line = f"▸ [{s.name}] {s.description}"
            if s.trigger:
                line += f"  (触发条件：{s.trigger})"
            lines.append(line)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "trigger": s.trigger,
                    "priority": s.priority,
                }
                for s in self._skills
            ]
        }

    @classmethod
    def from_dict(cls, d: dict, max_skills: int = 20) -> SkillsLibrary:
        lib = cls(max_skills=max_skills)
        for item in d.get("skills", []):
            lib.add(
                Skill(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    trigger=item.get("trigger", ""),
                    priority=item.get("priority", 5),
                )
            )
        return lib
