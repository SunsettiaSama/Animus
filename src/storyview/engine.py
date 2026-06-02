from __future__ import annotations

from storyview.gm.resolve import ActionResolver
from storyview.gm.scene import SceneComposer
from storyview.network import SceneNetwork
from storyview.store.mysql import StoryStoreBundle
from storyview.types import (
    NarrativeBrief,
    ResolvedOutcome,
    SceneCandidate,
    SceneLocateResult,
    ScenePacket,
    StoryBeat,
    StoryEventKind,
)
from storyview.worldview import StoryWorldview


class StoryEngine:
    """客观第二人称 GM 故事引擎。"""

    def __init__(
        self,
        stores: StoryStoreBundle,
        llm=None,
        *,
        worldview: StoryWorldview | None = None,
    ) -> None:
        self._stores = stores
        self._llm = llm
        self._worldview = worldview or StoryWorldview.default()
        self._scene_network = SceneNetwork(
            stores.scene.nodes,
            stores.scene.edges,
            runtime=stores,
        )
        self._scene = SceneComposer(stores, llm=llm, scene_network=self._scene_network)
        self._resolve = ActionResolver(stores, llm=llm)

    @property
    def worldview(self) -> StoryWorldview:
        return self._worldview

    @property
    def scene_network(self) -> SceneNetwork:
        return self._scene_network

    def set_llm(self, llm) -> None:
        self._llm = llm
        self._scene = SceneComposer(
            self._stores,
            llm=llm,
            scene_network=self._scene_network,
        )
        self._resolve = ActionResolver(self._stores, llm=llm)

    def ensure_world(self, world_id: str) -> None:
        wv = self._worldview
        self._stores.world.ensure(
            world_id,
            title=wv.title,
            era=wv.era,
            setting=wv.setting,
            tone=wv.tone,
            canon_json={
                "prefer": list(wv.canon),
                "forbidden": [],
                "must": [],
            },
        )
        self._stores.runtime.ensure(world_id)

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
        self.ensure_world(world_id)
        return self._scene_network.upsert_scene(
            world_id,
            name=name,
            narrative=narrative,
            location_id=location_id,
            tags=tags,
            scene_id=scene_id,
        )

    def link_scenes(
        self,
        world_id: str,
        *,
        from_scene_id: str,
        to_scene_id: str,
        transition_text: str,
        weight: int = 10,
    ) -> str:
        self.ensure_world(world_id)
        return self._scene_network.link_scenes(
            world_id,
            from_scene_id=from_scene_id,
            to_scene_id=to_scene_id,
            transition_text=transition_text,
            weight=weight,
        )

    def locate_scene(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> SceneLocateResult:
        self.ensure_world(world_id)
        return self._scene_network.locate(
            world_id,
            query,
            current_scene_id=current_scene_id,
        )

    def scene_inject_text(self, world_id: str, query: str = "") -> str:
        self.ensure_world(world_id)
        return self._scene_network.scene_inject_text(world_id, query)

    def locate_scene_candidates(
        self,
        world_id: str,
        query: str,
        *,
        limit: int = 3,
    ) -> list[SceneCandidate]:
        self.ensure_world(world_id)
        return self._scene_network.locate_candidates(world_id, query, limit=limit)

    def apply_scene(
        self,
        world_id: str,
        scene_id: str,
        *,
        transition_text: str = "",
    ) -> SceneLocateResult:
        from storyview.network.render import build_inject_text
        from storyview.types import StatePatch

        self.ensure_world(world_id)
        scene = self._scene_network.get(scene_id)
        if scene is None:
            raise ValueError(f"unknown scene: {scene_id}")
        if scene.location_id:
            self._stores.runtime.apply_patch(
                world_id,
                StatePatch(move_to_location_id=scene.location_id),
            )
        inject = build_inject_text(scene, transition_text=transition_text)
        snapshot = inject.strip() or scene.narrative.strip()
        if snapshot:
            self._stores.runtime.update_snapshot(world_id, snapshot)
        return SceneLocateResult(
            scene=scene,
            transition_text=transition_text,
            inject_text=inject,
            matched_by="applied",
        )

    def begin_event(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> ScenePacket:
        self.ensure_world(world_id)
        packet, _ = self._scene.open_scene(world_id, cue, kind=kind)
        return packet

    def resolve_event(
        self,
        event_id: str,
        *,
        intent: str,
        agent_narrative: str = "",
        with_dice: bool = True,
    ) -> ResolvedOutcome:
        return self._resolve.resolve(
            event_id,
            intent=intent,
            agent_narrative=agent_narrative,
            with_dice=with_dice,
        )

    def snapshot_scene(self, world_id: str, cue: str = "") -> str:
        self.ensure_world(world_id)
        return self._scene.snapshot(world_id, cue)

    def push_cue(self, world_id: str, cue: str) -> ResolvedOutcome | None:
        self.ensure_world(world_id)
        return self._resolve.push_cue(world_id, cue)

    def render_background(self, world_id: str, *, query: str = "", purpose: str = "") -> str:
        _ = purpose
        row = self._stores.world.get(world_id)
        if row is None:
            base = self._worldview.render()
        else:
            base = StoryWorldview.from_dict(
                {
                    "title": row.get("title") or self._worldview.title,
                    "setting": row.get("setting") or "",
                    "era": row.get("era") or "",
                    "tone": row.get("tone") or "",
                    "canon": self._stores.world.canon_rules(world_id).get("prefer") or [],
                }
            ).render()
        snap = self._stores.runtime.snapshot_text(world_id)
        parts = [base]
        scene_inject = self.scene_inject_text(world_id, query)
        if scene_inject.strip():
            parts.append(scene_inject.strip())
        elif snap.strip():
            parts.append(f"当前场景：\n{snap.strip()}")
        q = query.strip()
        if q:
            parts.append(f"当前叙事关注：{q}")
        return "\n\n".join(parts)

    def narrate(self, brief: NarrativeBrief) -> StoryBeat:
        world_id = "default"
        packet = self.begin_event(world_id, brief.hint or brief.query, kind=StoryEventKind.fabricate)
        outcome = self.resolve_event(
            packet.event_id,
            intent=brief.hint,
            agent_narrative=brief.profile_narrative,
            with_dice=bool(brief.dice_tendency),
        )
        return StoryBeat(
            text=outcome.resolution_text,
            emotion_label="",
            emotion_intensity=0.45,
            chapter_hint=brief.hint[:12] if brief.hint else "",
        )

    def collapse_experiences(self, lines: list[str]) -> str:
        parts = [line.strip() for line in lines if line and line.strip()]
        if not parts:
            return ""
        return "；".join(parts[:6])[:280]


StoryviewNarrativeEngine = StoryEngine
