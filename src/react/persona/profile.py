from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersonaProfile:
    name: str = "Assistant"
    background: str = ""
    traits: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    style: str = ""

    def render(self) -> str:
        parts = [f"【人物画像】{self.name}"]
        if self.background:
            parts.append(f"背景：{self.background}")
        if self.traits:
            parts.append("性格：" + "、".join(self.traits))
        if self.values:
            parts.append("价值观：" + "、".join(self.values))
        if self.style:
            parts.append(f"风格：{self.style}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "background": self.background,
            "traits": self.traits,
            "values": self.values,
            "style": self.style,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PersonaProfile:
        return cls(
            name=d.get("name", "Assistant"),
            background=d.get("background", ""),
            traits=d.get("traits", []),
            values=d.get("values", []),
            style=d.get("style", ""),
        )
