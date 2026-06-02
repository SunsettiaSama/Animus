from __future__ import annotations

from storyview import StoryWorldview
from storyview.bridge import StoryWorldContextBridge
from storyview.types import ScenePacket


class _FakePort:
    def __init__(self) -> None:
        self._packet = ScenePacket(
            event_id="e1",
            world_id="default",
            scene_text="你看见一扇半开的门。",
        )

    def last_scene(self, world_id: str):
        return self._packet

    def render_background(self, world_id: str, *, query: str = "", purpose: str = "") -> str:
        return StoryWorldview.default().render() + (f"\n\n当前叙事关注：{query}" if query else "")


def test_bridge_includes_scene():
    bridge = StoryWorldContextBridge(_FakePort(), world_id="default")

    class _Purpose:
        value = "fill"

    text = bridge.background(_Purpose(), query="午后")
    assert "你看见一扇半开的门" in text
    assert "午后" in text
