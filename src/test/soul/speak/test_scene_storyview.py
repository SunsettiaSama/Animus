from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.soul.speak.orchestrator.scene.apply import apply_story_scene
from agent.soul.speak.orchestrator.scene.collect import collect_story_scene
from agent.soul.speak.orchestrator.scene.layer import SpeakSceneLayer


@dataclass
class _Locate:
    scene: object | None
    transition_text: str = ""
    inject_text: str = ""
    matched_by: str = ""


@dataclass
class _Scene:
    id: str
    name: str


@dataclass
class _Bundle:
    session_id: str
    scene: SpeakSceneLayer = field(default_factory=SpeakSceneLayer)
    notes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def build_system(self) -> str:
        return "\n\n".join(self.scene.render_blocks())


class _FakeStoryPort:
    def scene_inject_text(self, world_id: str, query: str = "") -> str:
        return "【你所处的场景】\n你看到右手边有个茶壶。"

    def locate_scene(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> _Locate:
        _ = current_scene_id
        if "竹林" in query:
            return _Locate(
                scene=_Scene("scene-bamboo", "青竹坞"),
                transition_text="出门后，沿小路走十公里。",
                inject_text="【你所处的场景】\n你站在竹林边缘。",
                matched_by="edge",
            )
        return _Locate(
            scene=_Scene("scene-inner", "小酒馆内室"),
            transition_text="",
            inject_text="",
            matched_by="current",
        )

    def snapshot_scene(self, world_id: str, cue: str = "") -> str:
        return ""


def test_collect_story_scene_prefers_scene_inject_text():
    layer, meta = collect_story_scene(_FakeStoryPort(), "default", "你好")
    assert "茶壶" in layer.world_scene
    assert layer.scene_name == "小酒馆内室"
    assert meta["story_scene_id"] == "scene-inner"
    assert meta["story_scene_matched_by"] == "current"


def test_collect_story_scene_edge_locate_metadata():
    layer, meta = collect_story_scene(_FakeStoryPort(), "default", "去竹林")
    assert layer.scene_name == "青竹坞"
    assert "十公里" in layer.transition_text
    assert meta["story_scene_matched_by"] == "edge"


def test_apply_story_scene_writes_bundle_layer():
    bundle = _Bundle(session_id="s1")
    apply_story_scene(
        bundle,
        story_port=_FakeStoryPort(),
        world_id_fn=lambda: "default",
        user_text="你好",
    )
    assert "茶壶" in bundle.scene.world_scene
    assert bundle.meta["story_scene_name"] == "小酒馆内室"
    assert any("story_scene:" in note for note in bundle.notes)


def test_scene_layer_renders_into_system():
    bundle = _Bundle(session_id="s1")
    apply_story_scene(
        bundle,
        story_port=_FakeStoryPort(),
        world_id_fn=lambda: "default",
        user_text="你好",
    )
    assembled = bundle.build_system()
    assert "【你所处的场景】" in assembled
    assert "茶壶" in assembled
