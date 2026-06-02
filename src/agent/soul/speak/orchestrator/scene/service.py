from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.soul.speak.llm.engine import SpeakLLMEngine

from .collect import collect_story_scene
from .layer import SpeakSceneLayer
from .port import StoryScenePort
from .render import render_world_scene_block
from .resolve_llm import pick_scene_by_llm
from .resolve_regex import pick_scene_by_regex
from .state import SceneComposeState, SceneUpdateResult


@dataclass(frozen=True)
class SceneUpdateInput:
    session_id: str
    query: str
    turn_index: int = 0
    world_id: str = ""


class SceneComposeService:
    """场景编排服务：向 storyview 拉取候选 → 正则/LLM 判定 → 应用场景更新。"""

    def __init__(self, llm: SpeakLLMEngine | None = None) -> None:
        self._llm = llm or SpeakLLMEngine()
        self._story_port: StoryScenePort | None = None
        self._world_id_fn: Callable[[], str] | None = None
        self._version: dict[str, int] = {}
        self._active: dict[str, SceneComposeState] = {}
        self._last_query: dict[str, str] = {}

    def set_llm(self, llm: SpeakLLMEngine | None) -> None:
        self._llm = llm or SpeakLLMEngine()

    def bind_story(
        self,
        story_port: StoryScenePort | None,
        world_id_fn: Callable[[], str] | None = None,
    ) -> None:
        self._story_port = story_port
        self._world_id_fn = world_id_fn

    def has_story_binding(self) -> bool:
        return self._story_port is not None and self._world_id_fn is not None

    def _require_story(self) -> StoryScenePort:
        if self._story_port is None:
            raise RuntimeError("SceneComposeService 未绑定 story 端口")
        return self._story_port

    def _resolve_world_id(self, world_id: str) -> str:
        resolved = world_id.strip()
        if resolved:
            return resolved
        if self._world_id_fn is None:
            raise RuntimeError("SceneComposeService 未绑定 world_id_fn")
        return self._world_id_fn().strip()

    def active(self, session_id: str) -> SceneComposeState | None:
        return self._active.get(session_id.strip())

    def version(self, session_id: str) -> int | None:
        value = self._version.get(session_id.strip())
        return value if value else None

    def clear(self, session_id: str) -> None:
        key = session_id.strip()
        self._active.pop(key, None)
        self._version.pop(key, None)
        self._last_query.pop(key, None)

    def _next_version(self, session_id: str) -> int:
        key = session_id.strip()
        current = self._version.get(key, 0) + 1
        self._version[key] = current
        return current

    def _pick_candidate(
        self,
        query: str,
        candidates: tuple[Any, ...],
    ) -> tuple[Any | None, str]:
        if not candidates:
            return None, ""
        if len(candidates) == 1:
            return candidates[0], "single"
        index, method = pick_scene_by_regex(query, candidates)
        if index is not None:
            return candidates[index], method
        index, method = pick_scene_by_llm(self._llm, query, candidates)
        if index is not None:
            return candidates[index], method
        return None, ""

    def _build_layer(
        self,
        story: StoryScenePort,
        world_id: str,
        query: str,
        *,
        locate: Any,
    ) -> tuple[SpeakSceneLayer, dict[str, Any]]:
        layer, meta = collect_story_scene(story, world_id, query)
        if locate is None:
            return layer, meta
        scene = getattr(locate, "scene", None)
        if scene is not None:
            layer.scene_name = str(getattr(scene, "name", "") or "").strip()
            meta["story_scene_id"] = getattr(scene, "id", None)
        transition = str(getattr(locate, "transition_text", "") or "").strip()
        matched_by = str(getattr(locate, "matched_by", "") or "").strip()
        inject = str(getattr(locate, "inject_text", "") or "").strip()
        if transition:
            layer.transition_text = transition
        if matched_by:
            layer.matched_by = matched_by
            meta["story_scene_matched_by"] = matched_by
        if inject:
            if not inject.startswith("【"):
                inject = render_world_scene_block(inject)
            layer.world_scene = inject
        if layer.scene_name:
            meta["story_scene_name"] = layer.scene_name
        return layer, meta

    def update_scene(self, request: SceneUpdateInput) -> SceneUpdateResult:
        story = self._require_story()
        session_id = request.session_id.strip()
        query = request.query.strip()
        world_id = self._resolve_world_id(request.world_id)

        candidates = tuple(
            story.locate_scene_candidates(world_id, query, limit=3)
        )
        picked, resolve_method = self._pick_candidate(query, candidates)
        if picked is None:
            result = SceneUpdateResult(
                ok=False,
                resolve_method=resolve_method,
                candidates_count=len(candidates),
                query=query,
            )
            return result

        scene = picked.scene
        scene_id = str(getattr(scene, "id", "") or "").strip()
        transition_text = str(getattr(picked, "transition_text", "") or "").strip()
        locate = story.apply_scene(
            world_id,
            scene_id,
            transition_text=transition_text,
        )
        scene_name = str(getattr(scene, "name", "") or "").strip()
        inject_text = str(getattr(locate, "inject_text", "") or "").strip()
        matched_by = str(getattr(locate, "matched_by", "") or "").strip()
        result = SceneUpdateResult(
            ok=True,
            scene_id=scene_id or None,
            scene_name=scene_name,
            inject_text=inject_text,
            transition_text=transition_text,
            matched_by=matched_by,
            resolve_method=resolve_method,
            candidates_count=len(candidates),
            query=query,
            locate=locate,
        )
        layer, meta = self._build_layer(story, world_id, query, locate=locate)
        version = self._next_version(session_id)
        self._active[session_id] = SceneComposeState(
            version=version,
            result=result,
            layer=layer,
            meta=dict(meta),
        )
        self._last_query[session_id] = query
        return result

    def update_if_query_changed(self, request: SceneUpdateInput) -> SceneUpdateResult | None:
        session_id = request.session_id.strip()
        query = request.query.strip()
        if not query:
            return None
        if self._last_query.get(session_id) == query and self.active(session_id) is not None:
            return self.active(session_id).result
        return self.update_scene(request)
