from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .records import PersonaDistillRecord

PERSONA_DISTILL_HISTORY_MAX = 8


@dataclass
class PersonaComposeState:
    """自叙合成结果：稳定人格 + 近期状态蒸馏为一段第二人称自述。"""

    self_narrative: str
    stable_portrait: str
    state_portrait: str
    version: int
    updated_turn_index: int = 0
    injected_context: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "self_narrative": self.self_narrative,
            "stable_portrait": self.stable_portrait,
            "state_portrait": self.state_portrait,
            "version": self.version,
            "updated_turn_index": self.updated_turn_index,
            "injected_context": self.injected_context,
        }


@dataclass
class PersonaSessionRecord:
    current: PersonaComposeState | None = None
    last_stable: str = ""
    last_state: str = ""
    last_injected_context: str = ""
    last_dialogue_compressed: str = ""
    next_version: int = 1
    distill_history: list[PersonaDistillRecord] = field(default_factory=list)

    def append_distill(self, record: PersonaDistillRecord) -> None:
        self.distill_history.append(record)
        overflow = len(self.distill_history) - PERSONA_DISTILL_HISTORY_MAX
        if overflow > 0:
            del self.distill_history[:overflow]

    def recent_distill_history(self) -> tuple[PersonaDistillRecord, ...]:
        return tuple(self.distill_history[-PERSONA_DISTILL_HISTORY_MAX:])

    def has_compose_history(self) -> bool:
        return self.current is not None or bool(self.distill_history)
