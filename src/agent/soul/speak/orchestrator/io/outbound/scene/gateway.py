from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.speak.orchestrator.blocks.scene import SceneComposeService

if TYPE_CHECKING:
    from agent.soul.speak.orchestrator.bundle import SpeakPromptBundle


class OutboundSceneGateway:
    """Scene 出站：将场景更新结果注入 bundle，并暴露 version。"""

    def __init__(self, compose: SceneComposeService) -> None:
        self._compose = compose

    @property
    def service(self) -> SceneComposeService:
        return self._compose

    def version(self, session_id: str) -> int | None:
        return self._compose.version(session_id)

    def active(self, session_id: str):
        return self._compose.active(session_id)

    def snapshot(self, session_id: str) -> dict[str, object] | None:
        state = self._compose.active(session_id)
        if state is None:
            return None
        return {"world_scene": state.layer.world_scene}

    def apply_to_bundle(self, bundle: SpeakPromptBundle, session_id: str) -> bool:
        state = self._compose.active(session_id)
        if state is None or not state.result.ok:
            return False
        bundle.scene = state.layer
        bundle.meta.update(state.meta)
        bundle.meta["scene_compose_version"] = state.version
        bundle.meta["scene_resolve_method"] = state.result.resolve_method
        if state.result.scene_id:
            bundle.meta["story_scene_id"] = state.result.scene_id
        if state.result.scene_name:
            bundle.meta["story_scene_name"] = state.result.scene_name
        if state.result.matched_by:
            bundle.meta["story_scene_matched_by"] = state.result.matched_by
        note = (
            f"scene_compose: v={state.version} "
            f"method={state.result.resolve_method} "
            f"name={state.result.scene_name or '-'}"
        )
        bundle.notes.append(note)
        return True
