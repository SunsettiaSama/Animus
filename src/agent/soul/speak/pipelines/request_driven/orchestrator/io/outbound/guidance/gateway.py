from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.soul.speak.pipelines.request_driven.orchestrator.bundle import SpeakPromptBundle

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance import GuidanceControlService


class OutboundGuidanceGateway:
    """Guidance 出站：将引导叙述注入 bundle。"""

    def __init__(self, control: GuidanceControlService) -> None:
        self._control = control

    @property
    def control(self) -> GuidanceControlService:
        return self._control

    def snapshot(self, session_id: str) -> dict[str, Any] | None:
        return self._control.snapshot(session_id)

    def version(self, session_id: str) -> int | None:
        return self._control.version(session_id)

    def version_changed(self, session_id: str, *, since_version: int | None) -> bool:
        current = self.version(session_id)
        if since_version is None:
            return current is not None
        if current is None:
            return False
        return current > since_version

    def apply_to_bundle(self, bundle: SpeakPromptBundle, session_id: str) -> str | None:
        block = self._control.render_active(session_id)
        if block is None:
            return None
        bundle.guidance.control_arc = block
        state = self._control.active(session_id)
        if state is not None:
            bundle.notes.append(
                f"guidance: v={state.version} remaining={state.remaining_turns}"
            )
            bundle.meta["guidance_control_version"] = state.version
            bundle.meta["guidance_control_narrative"] = state.narrative
            bundle.meta["guidance_control_remaining"] = state.remaining_turns
            bundle.meta["guidance_emit_share_queue_index"] = state.emit_share_queue_index
            bundle.meta["guidance_emit_recall_unit_id"] = state.emit_recall_unit_id
        return block
