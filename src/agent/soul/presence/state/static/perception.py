from __future__ import annotations

from dataclasses import dataclass

from .narrative import compose_narrative, normalize_narrative


@dataclass
class PerceptionState:
    """对环境的感知：第二人称「你」自叙。"""

    narrative: str = ""

    def render(self) -> str:
        return normalize_narrative(self.narrative)

    def is_empty(self) -> bool:
        return not self.render()

    def copy(self) -> PerceptionState:
        return PerceptionState(narrative=self.narrative)

    def to_dict(self) -> dict:
        return {"narrative": self.narrative}

    @classmethod
    def from_dict(cls, d: dict) -> PerceptionState:
        if "narrative" in d:
            return cls(narrative=str(d.get("narrative", "")))
        scene = normalize_narrative(str(d.get("scene", "")))
        if not scene:
            setting = normalize_narrative(str(d.get("setting", "")))
            context = normalize_narrative(str(d.get("context", "")))
            scene = setting or context
            if setting and context:
                scene = f"{setting} · {context}"
        stimuli = [
            normalize_narrative(str(item))
            for item in d.get("stimuli", [])
            if normalize_narrative(str(item))
        ]
        parts: list[str] = []
        if scene:
            parts.append(f"你感知到{scene}")
        if stimuli:
            parts.append("周围有" + "、".join(stimuli))
        return cls(narrative=compose_narrative(*parts))
