from __future__ import annotations

from dataclasses import dataclass

from infra.agent.unit import Unit


@dataclass
class RhythmCardUnit(Unit):
    """导演节奏卡片：仅上下文，不硬改 gate。"""

    card: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "rhythm_card"
        if not self.source:
            self.source = "director"

    def render(self) -> str:
        text = self.card.strip()
        return f"[节奏卡片]\n{text}" if text else ""


@dataclass
class FateDiceUnit(Unit):
    """命运骰卡片：当前帧随机扰动提示，只注入上下文。"""

    roll: int = 0
    tendency: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "fate_dice"
        if not self.source:
            self.source = "director"

    def render(self) -> str:
        tendency = self.tendency.strip()
        lines = [f"[命运骰]", f"点数={int(self.roll)}"]
        if tendency:
            lines.append(f"倾向={tendency}")
        return "\n".join(lines)
