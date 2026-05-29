from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InteractorPortrait:
    """交互者核心画像，字段分层对齐 ``PersonaProfile``（面向用户而非 Agent 自身）。"""

    name: str = ""
    background_facts: list[str] = field(default_factory=list)
    core_traits: list[str] = field(default_factory=list)
    interpersonal_style: str = ""
    emotional_expressiveness: str = ""
    values: list[str] = field(default_factory=list)
    ethical_stances: list[str] = field(default_factory=list)
    cognitive_style: str = ""
    reasoning_pattern: str = ""
    core_motivation: str = ""
    avoidance_pattern: str = ""
    stress_response: str = ""
    boundaries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "background_facts": list(self.background_facts),
            "core_traits": list(self.core_traits),
            "interpersonal_style": self.interpersonal_style,
            "emotional_expressiveness": self.emotional_expressiveness,
            "values": list(self.values),
            "ethical_stances": list(self.ethical_stances),
            "cognitive_style": self.cognitive_style,
            "reasoning_pattern": self.reasoning_pattern,
            "core_motivation": self.core_motivation,
            "avoidance_pattern": self.avoidance_pattern,
            "stress_response": self.stress_response,
            "boundaries": list(self.boundaries),
        }

    @classmethod
    def from_dict(cls, data: dict) -> InteractorPortrait:
        background_facts = data.get("background_facts")
        if background_facts is None:
            bg = data.get("background", "")
            background_facts = [bg] if bg else []
        core_traits = data.get("core_traits")
        if core_traits is None:
            core_traits = data.get("traits", [])
        cognitive_style = data.get("cognitive_style", "") or data.get("style", "")
        return cls(
            name=str(data.get("name", "")),
            background_facts=list(background_facts or []),
            core_traits=list(core_traits or []),
            interpersonal_style=str(data.get("interpersonal_style", "")),
            emotional_expressiveness=str(data.get("emotional_expressiveness", "")),
            values=list(data.get("values") or []),
            ethical_stances=list(data.get("ethical_stances") or []),
            cognitive_style=str(cognitive_style),
            reasoning_pattern=str(data.get("reasoning_pattern", "")),
            core_motivation=str(data.get("core_motivation", "")),
            avoidance_pattern=str(data.get("avoidance_pattern", "")),
            stress_response=str(data.get("stress_response", "")),
            boundaries=list(data.get("boundaries") or []),
        )

    def render(self) -> str:
        parts: list[str] = []
        if self.name:
            parts.append(f"称呼：{self.name}")
        if self.background_facts:
            parts.append("事实背景：" + "；".join(self.background_facts))
        if self.core_traits:
            parts.append("特质：" + "、".join(self.core_traits))
        if self.interpersonal_style:
            parts.append(f"人际风格：{self.interpersonal_style}")
        if self.emotional_expressiveness:
            parts.append(f"情感表达：{self.emotional_expressiveness}")
        if self.values:
            parts.append("价值观：" + "、".join(self.values))
        if self.ethical_stances:
            parts.append("伦理立场：" + "、".join(self.ethical_stances))
        if self.cognitive_style:
            parts.append(f"认知：{self.cognitive_style}")
        if self.reasoning_pattern:
            parts.append(f"推理：{self.reasoning_pattern}")
        if self.core_motivation:
            parts.append(f"动机：{self.core_motivation}")
        if self.avoidance_pattern:
            parts.append(f"规避：{self.avoidance_pattern}")
        if self.stress_response:
            parts.append(f"压力应对：{self.stress_response}")
        if self.boundaries:
            parts.append("边界：" + "、".join(self.boundaries))
        return "\n".join(parts)
