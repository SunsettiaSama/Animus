from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Callable

from agent.soul.workers.domain_worker import DomainWorker

from storyview.engine import StoryEngine
from infra.storage import JsonStorageService
from storyview.store.mysql import StoryStoreBundle as MySQLStoryStoreBundle
from storyview.store.json import StoryStoreBundle as JsonStoryStoreBundle
from storyview.types import (
    AgentLocationSnapshot,
    ArcStartPolicy,
    GMAnswer,
    GMQuestion,
    ResolvedOutcome,
    SceneCandidate,
    SceneGroundingPolicy,
    SceneGroundingResult,
    SceneLocateResult,
    ScenePacket,
    SceneUnit,
    StoryBeatOutcome,
    StoryEventKind,
)


class StoryService(DomainWorker):
    """故事引擎 worker：所有 world 写操作经队列；同 world_id 串行。"""

    def __init__(
        self,
        mysql_client=None,
        llm=None,
        *,
        storage_backend: str = "mysql",
        json_root: str = ".react/soul_db",
    ) -> None:
        super().__init__("story-worker")
        if storage_backend.strip().lower() == "json":
            self._stores = JsonStoryStoreBundle(JsonStorageService(json_root))
        else:
            if mysql_client is None:
                raise RuntimeError("mysql story backend requires mysql_client")
            self._stores = MySQLStoryStoreBundle(mysql_client)
        self._engine = StoryEngine(self._stores, llm=llm)
        self._world_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._last_scene: dict[str, ScenePacket] = {}
        self._last_outcome: dict[str, StoryBeatOutcome] = {}

    @property
    def engine(self) -> StoryEngine:
        return self._engine

    @property
    def stores(self):
        return self._stores

    def init_schema(self) -> None:
        self._stores.init_schema()

    def set_llm(self, llm) -> None:
        self._engine.set_llm(llm)

    def last_scene(self, world_id: str) -> ScenePacket | None:
        return self._last_scene.get(world_id)

    def last_beat_outcome(self, world_id: str) -> StoryBeatOutcome | None:
        return self._last_outcome.get(world_id)

    def surprise_probability(self, world_id: str) -> float:
        future = self._run_world(
            world_id,
            lambda: self._engine.surprise_probability(world_id),
        )
        return future.result()

    def _world_lock(self, world_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._world_locks.get(world_id)
            if lock is None:
                lock = threading.Lock()
                self._world_locks[world_id] = lock
            return lock

    def _run_world(self, world_id: str, fn: Callable[[], object]) -> Future:
        future: Future = Future()

        def task() -> None:
            with self._world_lock(world_id):
                if future.cancelled():
                    return
                try:
                    future.set_result(fn())
                except BaseException as exc:
                    future.set_exception(exc)

        self.enqueue(task)
        return future

    def begin_event(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> Future[ScenePacket]:
        def _do() -> ScenePacket:
            packet = self._engine.begin_event(world_id, cue, kind=kind)
            self._last_scene[world_id] = packet
            return packet

        return self._run_world(world_id, _do)

    def resolve_event(
        self,
        event_id: str,
        *,
        intent: str,
        agent_narrative: str = "",
        with_dice: bool = True,
    ) -> Future[ResolvedOutcome]:
        event = self._stores.events.get(event_id)
        if event is None:
            raise ValueError(f"unknown story event: {event_id}")
        world_id = str(event["world_id"])

        def _do() -> ResolvedOutcome:
            return self._engine.resolve_event(
                event_id,
                intent=intent,
                agent_narrative=agent_narrative,
                with_dice=with_dice,
            )

        return self._run_world(world_id, _do)

    def snapshot_scene(self, world_id: str, cue: str = "") -> Future[str]:
        def _do() -> str:
            return self._engine.snapshot_scene(world_id, cue)

        return self._run_world(world_id, _do)

    def push_cue(self, world_id: str, cue: str) -> Future[ResolvedOutcome | None]:
        def _do() -> ResolvedOutcome | None:
            return self._engine.push_cue(world_id, cue)

        return self._run_world(world_id, _do)

    def render_background(self, world_id: str, *, query: str = "", purpose: str = "") -> str:
        future = self._run_world(
            world_id,
            lambda: self._engine.render_background(world_id, query=query, purpose=purpose),
        )
        return future.result()

    def upsert_scene(
        self,
        world_id: str,
        *,
        name: str,
        narrative: str,
        location_id: str | None = None,
        tags: list[str] | None = None,
        scene_id: str | None = None,
        meta: dict | None = None,
    ) -> Future[str]:
        return self._run_world(
            world_id,
            lambda: self._engine.upsert_scene(
                world_id,
                name=name,
                narrative=narrative,
                location_id=location_id,
                tags=tags,
                scene_id=scene_id,
                meta=meta,
            ),
        )

    def ground_scene_for_cue(
        self,
        world_id: str,
        cue: str,
        *,
        policy: SceneGroundingPolicy | None = None,
    ) -> Future[SceneGroundingResult]:
        return self._run_world(
            world_id,
            lambda: self._engine.ground_scene_for_cue(
                world_id,
                cue,
                policy=policy,
            ),
        )

    def link_scenes(
        self,
        world_id: str,
        *,
        from_scene_id: str,
        to_scene_id: str,
        transition_text: str,
        weight: int = 10,
    ) -> Future[str]:
        return self._run_world(
            world_id,
            lambda: self._engine.link_scenes(
                world_id,
                from_scene_id=from_scene_id,
                to_scene_id=to_scene_id,
                transition_text=transition_text,
                weight=weight,
            ),
        )

    def locate_scene(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> Future[SceneLocateResult]:
        return self._run_world(
            world_id,
            lambda: self._engine.locate_scene(
                world_id,
                query,
                current_scene_id=current_scene_id,
            ),
        )

    def scene_inject_text(self, world_id: str, query: str = "") -> Future[str]:
        return self._run_world(
            world_id,
            lambda: self._engine.scene_inject_text(world_id, query),
        )

    def locate_scene_candidates(
        self,
        world_id: str,
        query: str,
        *,
        limit: int = 3,
    ) -> Future[list[SceneCandidate]]:
        return self._run_world(
            world_id,
            lambda: self._engine.locate_scene_candidates(world_id, query, limit=limit),
        )

    def list_scenes(self, world_id: str) -> Future[list[SceneUnit]]:
        return self._run_world(
            world_id,
            lambda: self._engine.list_scenes(world_id),
        )

    def apply_scene(
        self,
        world_id: str,
        scene_id: str,
        *,
        transition_text: str = "",
    ) -> Future[SceneLocateResult]:
        return self._run_world(
            world_id,
            lambda: self._engine.apply_scene(
                world_id,
                scene_id,
                transition_text=transition_text,
            ),
        )

    def ask_gm(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
        start_policy: ArcStartPolicy | str = ArcStartPolicy.history,
    ) -> Future[GMQuestion]:
        return self._run_world(
            world_id,
            lambda: self._engine.ask_gm(
                world_id,
                cue,
                kind=kind,
                start_policy=start_policy,
            ),
        )

    def ask_gm_at_scene(
        self,
        world_id: str,
        scene_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> Future[GMQuestion]:
        return self._run_world(
            world_id,
            lambda: self._engine.ask_gm_at_scene(
                world_id,
                scene_id,
                cue,
                kind=kind,
            ),
        )

    def current_location_snapshot(
        self,
        world_id: str,
    ) -> Future[AgentLocationSnapshot | None]:
        return self._run_world(
            world_id,
            lambda: self._engine.current_location_snapshot(world_id),
        )

    def list_location_snapshots(
        self,
        world_id: str,
        *,
        limit: int = 10,
    ) -> Future[list[AgentLocationSnapshot]]:
        return self._run_world(
            world_id,
            lambda: self._engine.list_location_snapshots(world_id, limit=limit),
        )

    def answer_gm(
        self,
        question: GMQuestion,
        answer: GMAnswer,
        *,
        with_dice: bool = True,
    ) -> Future[StoryBeatOutcome]:
        world_id = question.world_id

        def _do() -> StoryBeatOutcome:
            outcome = self._engine.answer_gm(question, answer, with_dice=with_dice)
            self._last_scene[world_id] = outcome.scene_packet
            self._last_outcome[world_id] = outcome
            return outcome

        return self._run_world(world_id, _do)

    def ask_move(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> Future[GMQuestion | None]:
        return self._run_world(
            world_id,
            lambda: self._engine.ask_move(world_id, cue, kind=kind),
        )

    def answer_move(
        self,
        question: GMQuestion,
        answer: GMAnswer,
        *,
        with_dice: bool = False,
    ) -> Future[StoryBeatOutcome]:
        world_id = question.world_id

        def _do() -> StoryBeatOutcome:
            outcome = self._engine.answer_move(
                question,
                answer,
                with_dice=with_dice,
            )
            self._last_scene[world_id] = outcome.scene_packet
            self._last_outcome[world_id] = outcome
            return outcome

        return self._run_world(world_id, _do)

    def orchestrate_beat(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
        answer_text: str | None = None,
        with_dice: bool = True,
    ) -> Future[StoryBeatOutcome]:
        def _do() -> StoryBeatOutcome:
            outcome = self._engine.orchestrate_beat(
                world_id,
                cue,
                kind=kind,
                answer_text=answer_text,
                with_dice=with_dice,
            )
            self._last_scene[world_id] = outcome.scene_packet
            self._last_outcome[world_id] = outcome
            return outcome

        return self._run_world(world_id, _do)

    def tick_surprise(
        self,
        world_id: str,
        elapsed_sec: float,
    ) -> Future[StoryBeatOutcome | None]:
        def _do() -> StoryBeatOutcome | None:
            outcome = self._engine.tick_surprise(world_id, elapsed_sec)
            if outcome is not None:
                self._last_scene[world_id] = outcome.scene_packet
                self._last_outcome[world_id] = outcome
            return outcome

        return self._run_world(world_id, _do)

    def ask_surprise(
        self,
        world_id: str,
        elapsed_sec: float,
    ) -> Future[GMQuestion | None]:
        return self._run_world(
            world_id,
            lambda: self._engine.ask_surprise(world_id, elapsed_sec),
        )

    def distill_arc(
        self,
        world_id: str,
        outcomes: list[StoryBeatOutcome],
    ) -> Future[str]:
        return self._run_world(
            world_id,
            lambda: self._engine.distill_arc(world_id, outcomes),
        )
