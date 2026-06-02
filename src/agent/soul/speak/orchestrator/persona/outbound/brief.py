from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.speak.orchestrator.io import OrchestratorIOHub
    from agent.soul.speak.orchestrator.persona import SpeakPersonaLayer


@dataclass(frozen=True)
class PersonaOutboundBrief:
    """Orchestrator persona 出站摘要，供 guidance 入站规划读取。"""

    self_narrative: str = ""
    stable_portrait: str = ""
    state_portrait: str = ""
    instant_mood: str = ""
    compose_version: int | None = None
    recent_distill_lines: tuple[str, ...] = ()
    injected_context: str = ""

    @property
    def portrait_for_planner(self) -> str:
        return self.self_narrative.strip() or self.stable_portrait.strip()

    def snapshot(self) -> dict[str, object]:
        return {
            "self_narrative": self.self_narrative,
            "stable_portrait": self.stable_portrait,
            "state_portrait": self.state_portrait,
            "instant_mood": self.instant_mood,
            "compose_version": self.compose_version,
            "recent_distill_lines": list(self.recent_distill_lines),
            "injected_context": self.injected_context,
        }


def collect_persona_outbound_brief(
    io: OrchestratorIOHub,
    *,
    session_id: str,
    layer: SpeakPersonaLayer,
) -> PersonaOutboundBrief:
    entry = io.inbound.persona.session_record(session_id)
    state = io.outbound.persona.service.active(session_id)
    history_lines: list[str] = []
    for record in entry.recent_distill_history()[-3:]:
        text = record.text.strip()
        if not text:
            continue
        history_lines.append(f"turn{record.turn_index}: {text}")
    injected = ""
    version: int | None = None
    state_portrait = layer.state_portrait.strip()
    if state is not None:
        injected = state.injected_context.strip()
        version = state.version
        if not state_portrait:
            state_portrait = state.state_portrait.strip()
    return PersonaOutboundBrief(
        self_narrative=layer.self_narrative.strip(),
        stable_portrait=layer.stable_portrait.strip(),
        state_portrait=state_portrait,
        instant_mood=layer.instant_mood.strip(),
        compose_version=version,
        recent_distill_lines=tuple(history_lines),
        injected_context=injected,
    )
