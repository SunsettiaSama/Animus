from __future__ import annotations

from storyview.service import StoryService
from storyview.types import (
    GMAnswer,
    GMQuestion,
    ResolvedOutcome,
    SceneCandidate,
    SceneLocateResult,
    ScenePacket,
    StoryBeatOutcome,
    StoryEventKind,
)


class StoryPort:
    """Soul 侧访问故事引擎的唯一入口。"""

    def __init__(self, service: StoryService) -> None:
        if service is None:
            raise RuntimeError("StoryPort requires StoryService")
        self._service = service

    @property
    def service(self) -> StoryService:
        return self._service

    def begin_event(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> ScenePacket:
        return self._service.begin_event(world_id, cue, kind=kind).result()

    def resolve_event(
        self,
        event_id: str,
        *,
        intent: str,
        agent_narrative: str = "",
        with_dice: bool = True,
    ) -> ResolvedOutcome:
        return self._service.resolve_event(
            event_id,
            intent=intent,
            agent_narrative=agent_narrative,
            with_dice=with_dice,
        ).result()

    def snapshot_scene(self, world_id: str, cue: str = "") -> str:
        return self._service.snapshot_scene(world_id, cue).result()

    def push_cue(self, world_id: str, cue: str) -> ResolvedOutcome | None:
        return self._service.push_cue(world_id, cue).result()

    def last_scene(self, world_id: str) -> ScenePacket | None:
        return self._service.last_scene(world_id)

    def last_beat_outcome(self, world_id: str) -> StoryBeatOutcome | None:
        return self._service.last_beat_outcome(world_id)

    def surprise_probability(self, world_id: str) -> float:
        return self._service.surprise_probability(world_id)

    def render_background(self, world_id: str, *, query: str = "", purpose: str = "") -> str:
        return self._service.render_background(world_id, query=query, purpose=purpose)

    def upsert_scene(
        self,
        world_id: str,
        *,
        name: str,
        narrative: str,
        location_id: str | None = None,
        tags: list[str] | None = None,
        scene_id: str | None = None,
    ) -> str:
        return self._service.upsert_scene(
            world_id,
            name=name,
            narrative=narrative,
            location_id=location_id,
            tags=tags,
            scene_id=scene_id,
        ).result()

    def link_scenes(
        self,
        world_id: str,
        *,
        from_scene_id: str,
        to_scene_id: str,
        transition_text: str,
        weight: int = 10,
    ) -> str:
        return self._service.link_scenes(
            world_id,
            from_scene_id=from_scene_id,
            to_scene_id=to_scene_id,
            transition_text=transition_text,
            weight=weight,
        ).result()

    def locate_scene(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> SceneLocateResult:
        return self._service.locate_scene(
            world_id,
            query,
            current_scene_id=current_scene_id,
        ).result()

    def scene_inject_text(self, world_id: str, query: str = "") -> str:
        return self._service.scene_inject_text(world_id, query).result()

    def locate_scene_candidates(
        self,
        world_id: str,
        query: str,
        *,
        limit: int = 3,
    ) -> list[SceneCandidate]:
        return self._service.locate_scene_candidates(
            world_id,
            query,
            limit=limit,
        ).result()

    def apply_scene(
        self,
        world_id: str,
        scene_id: str,
        *,
        transition_text: str = "",
    ) -> SceneLocateResult:
        return self._service.apply_scene(
            world_id,
            scene_id,
            transition_text=transition_text,
        ).result()

    def ask_gm(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> GMQuestion:
        return self._service.ask_gm(world_id, cue, kind=kind).result()

    def answer_gm(
        self,
        question: GMQuestion,
        answer: GMAnswer,
        *,
        with_dice: bool = True,
    ) -> StoryBeatOutcome:
        return self._service.answer_gm(
            question,
            answer,
            with_dice=with_dice,
        ).result()

    def ask_move(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> GMQuestion | None:
        return self._service.ask_move(world_id, cue, kind=kind).result()

    def answer_move(
        self,
        question: GMQuestion,
        answer: GMAnswer,
        *,
        with_dice: bool = False,
    ) -> StoryBeatOutcome:
        return self._service.answer_move(
            question,
            answer,
            with_dice=with_dice,
        ).result()

    def orchestrate_beat(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
        answer_text: str | None = None,
        with_dice: bool = True,
    ) -> StoryBeatOutcome:
        return self._service.orchestrate_beat(
            world_id,
            cue,
            kind=kind,
            answer_text=answer_text,
            with_dice=with_dice,
        ).result()

    def tick_surprise(
        self,
        world_id: str,
        elapsed_sec: float,
    ) -> StoryBeatOutcome | None:
        return self._service.tick_surprise(world_id, elapsed_sec).result()

    def ask_surprise(
        self,
        world_id: str,
        elapsed_sec: float,
    ) -> GMQuestion | None:
        return self._service.ask_surprise(world_id, elapsed_sec).result()

    def distill_arc(
        self,
        world_id: str,
        outcomes: list[StoryBeatOutcome],
    ) -> str:
        return self._service.distill_arc(world_id, outcomes).result()


StoryLifePort = StoryPort
