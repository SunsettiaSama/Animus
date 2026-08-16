from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.speak.responders.request_driven.orchestrator.blocks.persona import (
    PersonaComposeService,
    SpeakPersonaLayer,
)

if TYPE_CHECKING:
    from agent.soul.speak.responders.request_driven.orchestrator.bundle import SpeakPromptBundle


class OutboundPersonaGateway:
    """Persona 出站：将自叙状态注入 layer / bundle，并暴露 version 供 orchestrator 对比。"""

    def __init__(self, compose: PersonaComposeService) -> None:
        self._compose = compose

    @property
    def service(self) -> PersonaComposeService:
        return self._compose

    def snapshot(self, session_id: str) -> dict[str, object] | None:
        return self._compose.snapshot(session_id)

    def version(self, session_id: str) -> int | None:
        return self._compose.version(session_id)

    def version_changed(self, session_id: str, *, since_version: int | None) -> bool:
        current = self.version(session_id)
        if since_version is None:
            return current is not None
        if current is None:
            return False
        return current > since_version

    def build_layer(self, session_id: str) -> SpeakPersonaLayer:
        state = self._compose.active(session_id)
        if state is None:
            # 用户热路径可能尚未异步 compose；空层放行，不阻塞角色接口
            return SpeakPersonaLayer()
        return SpeakPersonaLayer.from_compose(state)

    def apply_to_layer(
        self,
        layer: SpeakPersonaLayer,
        session_id: str,
    ) -> SpeakPersonaLayer:
        state = self._compose.active(session_id)
        if state is None:
            # 拿不到 persona compose 结果就先用当前层；完整刷新走异步 warm
            return layer
        merged = SpeakPersonaLayer.from_compose(state)
        merged.presence.instant_mood = layer.presence.instant_mood
        merged.dialogue_compressed = layer.dialogue_compressed
        return merged

    def apply_to_bundle(self, bundle: SpeakPromptBundle, session_id: str) -> str:
        layer = self.apply_to_layer(bundle.persona, session_id)
        bundle.persona = layer
        state = self._compose.active(session_id)
        if state is not None:
            bundle.meta["persona_compose_version"] = state.version
            bundle.notes.append(f"persona_compose: v={state.version}")
        return layer.self_narrative
