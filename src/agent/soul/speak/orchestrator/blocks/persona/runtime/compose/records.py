from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonaDistillRecord:
    """会话内过往 persona 蒸馏/自叙记录，供下一轮增量修订。"""

    turn_index: int
    text: str
    kind: str = "narrative"

    def snapshot(self) -> dict[str, object]:
        return {
            "turn_index": self.turn_index,
            "text": self.text,
            "kind": self.kind,
        }
