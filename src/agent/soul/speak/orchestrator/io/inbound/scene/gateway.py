from __future__ import annotations

from agent.soul.speak.orchestrator.blocks.scene import SceneComposeService, SceneUpdateInput

from .request import SceneUpdateRequest


class InboundSceneGateway:
    """Scene 入站：接收场景更新请求，触发 storyview 候选检索与判定。"""

    def __init__(self, compose: SceneComposeService) -> None:
        self._compose = compose

    @property
    def service(self) -> SceneComposeService:
        return self._compose

    def _to_input(self, request: SceneUpdateRequest) -> SceneUpdateInput:
        return SceneUpdateInput(
            session_id=request.session_id,
            query=request.query,
            turn_index=request.turn_index,
            world_id=request.world_id,
        )

    def update(self, request: SceneUpdateRequest):
        return self._compose.update_scene(self._to_input(request))

    def sync_for_turn(
        self,
        request: SceneUpdateRequest,
        *,
        force: bool = False,
    ):
        if not self._compose.has_story_binding():
            return None
        if force or request.force:
            return self.update(request)
        return self._compose.update_if_query_changed(self._to_input(request))

    def clear(self, session_id: str) -> None:
        self._compose.clear(session_id)
