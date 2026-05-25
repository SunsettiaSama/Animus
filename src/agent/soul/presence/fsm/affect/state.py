from __future__ import annotations

from dataclasses import dataclass

from ..narrative import compose_narrative, normalize_narrative


@dataclass
class AffectState:
    """情感：第一人称自叙。"""

    narrative: str = ""

    def render(self) -> str:
        return normalize_narrative(self.narrative)

    def is_empty(self) -> bool:
        return not self.render()

    def append(self, line: str, *, max_chars: int = 800) -> None:
        text = normalize_narrative(line)
        if not text:
            return
        if self.narrative:
            self.narrative = f"{self.narrative}\n{text}"
        else:
            self.narrative = text
        if max_chars > 0 and len(self.narrative) > max_chars:
            self.narrative = self.narrative[-max_chars:]

    def copy(self) -> AffectState:
        return AffectState(narrative=self.narrative)

    def to_dict(self) -> dict:
        return {"narrative": self.narrative}

    @classmethod
    def from_dict(cls, d: dict) -> AffectState:
        if "narrative" in d:
            return cls(narrative=str(d.get("narrative", "")))
        parts: list[str] = []
        mood = normalize_narrative(str(d.get("mood", "") or d.get("texture", "")))
        if mood:
            parts.append(mood)
        valence = normalize_narrative(str(d.get("valence", "")))
        if valence:
            parts.append(f"我感到{valence}")
        for anchor in d.get("anchors", []):
            if not isinstance(anchor, dict):
                continue
            felt = normalize_narrative(str(anchor.get("felt", "") or anchor.get("event", "")))
            if felt:
                parts.append(felt)
        return cls(narrative=compose_narrative(*parts))
