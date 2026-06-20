from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.orchestrator.blocks.persona import PersonaDistillRecord


@dataclass(frozen=True)
class PersonaComposeRequest:
    """Persona 入站请求：供 orchestrator 在 prepare / finish_turn 注入上下文。"""

    session_id: str
    turn_index: int = 0
    force: bool = False
    injected_context: str = ""
    dialogue_compressed: str = ""
    distill_history: tuple[PersonaDistillRecord, ...] = ()
