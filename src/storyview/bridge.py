from __future__ import annotations

from storyview.port import StoryPort
from storyview.service import StoryService


class StoryWorldContextBridge:
    """对接 soul.life.StoryWorldContextSupplier，注入故事引擎客观背景。"""

    def __init__(self, port: StoryPort, *, world_id: str) -> None:
        self._port = port
        self._world_id = world_id

    def set_world_id(self, world_id: str) -> None:
        self._world_id = world_id

    def background(
        self,
        purpose,
        *,
        query: str = "",
    ) -> str:
        purpose_value = getattr(purpose, "value", str(purpose))
        packet = self._port.last_scene(self._world_id)
        if packet is not None and packet.scene_text.strip():
            base = self._port.render_background(
                self._world_id,
                query=query,
                purpose=purpose_value,
            )
            return f"{base}\n\n当前客观场景：\n{packet.scene_text.strip()}"
        return self._port.render_background(
            self._world_id,
            query=query,
            purpose=purpose_value,
        )
