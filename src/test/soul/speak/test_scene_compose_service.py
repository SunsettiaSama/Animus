from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3]


def _ensure_pkg(name: str) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = module


def _load(rel_path: str, full_name: str):
    parent = full_name.rsplit(".", 1)[0]
    _ensure_pkg(parent)
    path = _SRC / rel_path
    spec = importlib.util.spec_from_file_location(full_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {full_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


for pkg in (
    "agent",
    "agent.soul",
    "agent.soul.speak",
    "agent.soul.speak.llm",
    "agent.soul.speak.pipelines.request_driven.orchestrator",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime",
):
    _ensure_pkg(pkg)

_load("agent/soul/speak/llm/engine.py", "agent.soul.speak.llm.engine")
_load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/layer.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.layer",
)
_load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/port.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.port",
)
_load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/render.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.render",
)
_load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/collect.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.collect",
)
_load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/state.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.state",
)
_load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/resolve_regex.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.resolve_regex",
)
_load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/resolve_llm.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.resolve_llm",
)
_service = _load(
    "agent/soul/speak/pipelines/request_driven/orchestrator/blocks/scene/runtime/service.py",
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.service",
)

pick_scene_by_regex = sys.modules[
    "agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene.runtime.resolve_regex"
].pick_scene_by_regex
SceneComposeService = _service.SceneComposeService
SceneUpdateInput = _service.SceneUpdateInput


@dataclass
class _Scene:
    id: str
    name: str
    narrative: str = ""
    tags: tuple[str, ...] = ()


@dataclass
class _Candidate:
    scene: _Scene
    transition_text: str = ""
    matched_by: str = ""
    score: int = 0


@dataclass
class _Locate:
    scene: _Scene | None
    transition_text: str = ""
    inject_text: str = ""
    matched_by: str = ""


class _MemoryStoryPort:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str, str]] = []

    def scene_inject_text(self, world_id: str, query: str = "") -> str:
        return ""

    def locate_scene(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> _Locate:
        return _Locate(scene=None)

    def snapshot_scene(self, world_id: str, cue: str = "") -> str:
        return ""

    def locate_scene_candidates(
        self,
        world_id: str,
        query: str,
        *,
        limit: int = 3,
    ) -> list[_Candidate]:
        inner = _Candidate(
            scene=_Scene("scene-inner", "小酒馆内室", "你看到茶壶。"),
            matched_by="current",
            score=1,
        )
        bamboo = _Candidate(
            scene=_Scene("scene-bamboo", "青竹坞", "你站在竹林边缘。", tags=("竹林",)),
            transition_text="沿小路走十公里到青竹坞。",
            matched_by="edge",
            score=5,
        )
        if "竹林" in query or "青竹坞" in query:
            return [bamboo, inner][:limit]
        return [inner][:limit]

    def apply_scene(
        self,
        world_id: str,
        scene_id: str,
        *,
        transition_text: str = "",
    ) -> _Locate:
        self.applied.append((world_id, scene_id, transition_text))
        if scene_id == "scene-bamboo":
            scene = _Scene("scene-bamboo", "青竹坞", "你站在竹林边缘。")
            return _Locate(
                scene=scene,
                transition_text=transition_text,
                inject_text="【你所处的场景】\n你站在竹林边缘。",
                matched_by="applied",
            )
        scene = _Scene("scene-inner", "小酒馆内室", "你看到茶壶。")
        return _Locate(
            scene=scene,
            inject_text="【你所处的场景】\n你看到茶壶。",
            matched_by="applied",
        )


def test_pick_scene_by_regex_name_substr():
    candidates = (
        _Candidate(_Scene("a", "小酒馆内室")),
        _Candidate(_Scene("b", "青竹坞", tags=("竹林",))),
    )
    index, method = pick_scene_by_regex("我想去青竹坞看看", candidates)
    assert index == 1
    assert method == "regex_name_substr"


def test_pick_scene_by_regex_tag():
    candidates = (
        _Candidate(_Scene("a", "甲", tags=("酒馆",))),
        _Candidate(_Scene("b", "乙", tags=("竹林",))),
    )
    index, method = pick_scene_by_regex("风过竹林沙沙响", candidates)
    assert index == 1
    assert method == "regex_tag"


def test_scene_compose_service_regex_then_apply():
    port = _MemoryStoryPort()
    service = SceneComposeService()
    service.bind_story(port, lambda: "default")
    result = service.update_scene(
        SceneUpdateInput(session_id="s1", query="去青竹坞")
    )
    assert result.ok is True
    assert result.scene_name == "青竹坞"
    assert result.resolve_method == "regex_name_substr"
    assert port.applied == [("default", "scene-bamboo", "沿小路走十公里到青竹坞。")]
    state = service.active("s1")
    assert state is not None
    assert "竹林" in state.layer.world_scene


def test_scene_compose_service_skips_duplicate_query():
    port = _MemoryStoryPort()
    service = SceneComposeService()
    service.bind_story(port, lambda: "default")
    service.update_scene(SceneUpdateInput(session_id="s1", query="去青竹坞"))
    port.applied.clear()
    service.update_if_query_changed(
        SceneUpdateInput(session_id="s1", query="去青竹坞")
    )
    assert port.applied == []
