from __future__ import annotations

from dataclasses import dataclass

from .records import PersonaDistillRecord


@dataclass(frozen=True)
class PersonaComposeInput:
    """Persona 域规划输入（由 IO 请求映射，供 compose 服务消费）。"""

    session_id: str
    turn_index: int = 0
    force: bool = False
    injected_context: str = ""
    dialogue_compressed: str = ""
    distill_history: tuple[PersonaDistillRecord, ...] = ()
