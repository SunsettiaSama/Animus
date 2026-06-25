from __future__ import annotations

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.persona import (
    PersonaComposeInput,
    PersonaComposeService,
)

from .request import PersonaComposeRequest


class InboundPersonaGateway:
    """Persona 入站：接收 compose 上下文，触发稳定人格 + 自叙修订。"""

    def __init__(self, compose: PersonaComposeService) -> None:
        self._compose = compose

    @property
    def service(self) -> PersonaComposeService:
        return self._compose

    def session_record(self, session_id: str):
        return self._compose.session_record(session_id)

    def _to_compose_input(self, request: PersonaComposeRequest) -> PersonaComposeInput:
        entry = self._compose.session_record(request.session_id)
        history = request.distill_history
        if not history:
            history = entry.recent_distill_history()
        return PersonaComposeInput(
            session_id=request.session_id,
            turn_index=request.turn_index,
            force=request.force,
            injected_context=request.injected_context,
            dialogue_compressed=request.dialogue_compressed,
            distill_history=history,
        )

    def compose(self, request: PersonaComposeRequest):
        return self._compose.compose_and_set(self._to_compose_input(request))

    def sync_for_compose(
        self,
        request: PersonaComposeRequest,
        *,
        force: bool = False,
    ) -> bool:
        entry = self._compose.session_record(request.session_id)
        active = self._compose.active(request.session_id)
        injected = request.injected_context.strip()
        dialogue = request.dialogue_compressed.strip()
        if force or request.force:
            self.compose(request)
            return True
        if active is None and not entry.has_compose_history():
            self.compose(request)
            return True
        if (
            entry.last_injected_context != injected
            or entry.last_dialogue_compressed != dialogue
        ):
            self.compose(request)
            return True
        return False

    def clear(self, session_id: str) -> None:
        self._compose.clear(session_id)
