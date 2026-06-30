from __future__ import annotations

from storyview.scene.cards import cards_from_meta, cards_to_meta
from storyview.scene.drafting import SceneDraftingEngine
from storyview.types import (
    SceneCandidate,
    SceneGroundingPolicy,
    SceneGroundingResult,
    SceneGroundingTraceEntry,
    SceneNodeMutation,
    SceneReviewStatus,
    SceneUnit,
)
from storyview.world.inspector import WorldviewInspector
from storyview.world.provider import WorldviewProvider


class SceneGroundingService:
    def __init__(
        self,
        stores,
        scene_network,
        *,
        worldview_provider: WorldviewProvider | None = None,
        inspector: WorldviewInspector | None = None,
        drafter: SceneDraftingEngine | None = None,
        llm=None,
    ) -> None:
        self._stores = stores
        self._scene_network = scene_network
        self._provider = worldview_provider or WorldviewProvider(stores)
        self._inspector = inspector or WorldviewInspector(self._provider, llm=llm)
        self._drafter = drafter or SceneDraftingEngine(self._provider, llm=llm)

    def ground_scene_for_cue(
        self,
        world_id: str,
        cue: str,
        *,
        policy: SceneGroundingPolicy | None = None,
    ) -> SceneGroundingResult:
        cfg = policy or SceneGroundingPolicy()
        trace: list[SceneGroundingTraceEntry] = []
        candidates = self._scene_network.locate_candidates(world_id, cue, limit=5)
        best = self._select_existing_candidate(candidates, cfg.match_threshold)
        if best is not None:
            scene = best.scene
            cards = cards_from_meta(scene.meta)
            trace.append(
                SceneGroundingTraceEntry(
                    round=1,
                    action="match_existing",
                    observation=f"命中 {scene.name} via {best.matched_by} score={best.score}",
                )
            )
            if len(cards) < 3:
                return SceneGroundingResult(
                    scene_id="",
                    scene_name=scene.name,
                    matched_by=best.matched_by,
                    score=best.score,
                    blocked_reason=f"matched scene lacks interactive cards: {scene.id}",
                    trace=tuple(trace),
                    narrative=scene.narrative,
                )
            return SceneGroundingResult(
                scene_id=scene.id,
                scene_name=scene.name,
                matched_by=best.matched_by,
                score=best.score,
                created=False,
                cards=tuple(cards),
                trace=tuple(trace),
                narrative=scene.narrative,
            )
        if not cfg.allow_create:
            return SceneGroundingResult(
                scene_id="",
                scene_name="",
                blocked_reason="无匹配 scene 且 allow_create=False",
                trace=tuple(trace),
            )
        existing_scenes = self._scene_network.list_scenes(world_id)
        draft = self._drafter.draft_for_cue(
            world_id,
            cue,
            existing_scenes=existing_scenes,
            allow_node_mutation=cfg.allow_node_mutation,
        )
        trace.append(
            SceneGroundingTraceEntry(
                round=1,
                action="draft_scene",
                observation=f"生成草案 {draft.name} cards={len(draft.cards)}",
            )
        )
        if draft.reasoning == "llm_unfinished":
            return SceneGroundingResult(
                scene_id="",
                scene_name="",
                blocked_reason="scene drafter did not finish",
                trace=tuple(trace),
            )
        anchor_scene_id = self._resolve_anchor_scene_id(world_id, cfg.attach_to_current)
        anchor_context = ""
        if anchor_scene_id:
            anchor_scene = self._scene_network.get(anchor_scene_id)
            anchor_name = anchor_scene.name if anchor_scene is not None else anchor_scene_id
            anchor_context = (
                "\n【计划挂载】\n"
                f"如果草案通过审查，grounding service 会在写入后创建边："
                f"{anchor_name}({anchor_scene_id}) -> 新场景。"
            )
        context = self._provider.existing_context(
            world_id,
            current_scene_id=anchor_scene_id,
            query=cue,
            include_mutation_actions=cfg.allow_node_mutation,
        ) + anchor_context
        review_round = 0
        approved = False
        while review_round < cfg.max_review_rounds:
            review_round += 1
            review = self._inspector.review_scene_draft(
                world_id,
                cue,
                draft,
                context=context,
            )
            trace.append(
                SceneGroundingTraceEntry(
                    round=review_round,
                    action="inspect_worldview",
                    observation=f"{review.status}: {review.reason}",
                )
            )
            if review.patches:
                trace.append(
                    SceneGroundingTraceEntry(
                        round=review_round,
                        action="worldview_patch",
                        observation="; ".join(
                            f"{patch.field}={patch.value or ','.join(patch.items)}"
                            for patch in review.patches
                        ),
                    )
                )
            if review.status == SceneReviewStatus.approved and review.approved_draft is not None:
                draft = review.approved_draft
                approved = True
                break
            if review.status == SceneReviewStatus.rejected:
                return SceneGroundingResult(
                    scene_id="",
                    scene_name="",
                    blocked_reason=review.reason or "scene draft rejected",
                    trace=tuple(trace),
                )
            draft = self._drafter.draft_for_cue(
                world_id,
                cue,
                existing_scenes=existing_scenes,
                revision_reason=review.reason,
                revision_patches=review.patches,
                prior_draft=draft,
                allow_node_mutation=cfg.allow_node_mutation,
            )
            if draft.reasoning == "llm_unfinished":
                return SceneGroundingResult(
                    scene_id="",
                    scene_name="",
                    blocked_reason="scene drafter did not finish revision",
                    trace=tuple(trace),
                )
        if not approved:
            return SceneGroundingResult(
                scene_id="",
                scene_name="",
                blocked_reason="scene draft review did not approve",
                trace=tuple(trace),
            )
        if len(draft.cards) < 3:
            return SceneGroundingResult(
                scene_id="",
                scene_name="",
                blocked_reason="scene draft 未通过审查或未生成足够 cards",
                trace=tuple(trace),
            )
        if cfg.allow_node_mutation and draft.node_mutations:
            trace.extend(self._apply_node_mutations(world_id, draft.node_mutations))
        final_anchor_scene_id = (
            self._resolve_anchor_from_draft_edges(world_id, draft.edges)
            or anchor_scene_id
        )
        if final_anchor_scene_id is None and cfg.attach_to_current:
            return SceneGroundingResult(
                scene_id="",
                scene_name="",
                blocked_reason="无法找到 current/home scene 以挂载新 scene",
                trace=tuple(trace),
            )
        meta = cards_to_meta(list(draft.cards))
        scene_id = self._scene_network.upsert_scene(
            world_id,
            name=draft.name,
            narrative=draft.narrative,
            tags=list(draft.tags),
            meta=meta,
        )
        if final_anchor_scene_id:
            self._scene_network.link_scenes(
                world_id,
                from_scene_id=final_anchor_scene_id,
                to_scene_id=scene_id,
                transition_text=f"前往 {draft.name}",
                weight=12,
            )
            trace.append(
                SceneGroundingTraceEntry(
                    round=review_round + 1,
                    action="link_scene",
                    observation=f"{final_anchor_scene_id} -> {scene_id}",
                )
            )
        trace.append(
            SceneGroundingTraceEntry(
                round=review_round + 1,
                action="upsert_scene",
                observation=f"写入 scene {scene_id}",
            )
        )
        return SceneGroundingResult(
            scene_id=scene_id,
            scene_name=draft.name,
            matched_by="created",
            score=0,
            created=True,
            cards=tuple(draft.cards),
            trace=tuple(trace),
            narrative=draft.narrative,
        )

    def get_scene_cards(self, scene_id: str) -> list:
        scene = self._scene_network.get(scene_id)
        if scene is None:
            return []
        return cards_from_meta(scene.meta)

    def _select_existing_candidate(
        self,
        candidates: list[SceneCandidate],
        threshold: int,
    ) -> SceneCandidate | None:
        for candidate in candidates:
            if candidate.matched_by == "current" and candidate.score <= 0:
                continue
            if candidate.score >= threshold:
                return candidate
        return None

    def _resolve_anchor_scene_id(
        self,
        world_id: str,
        attach_to_current: bool,
    ) -> str | None:
        if not attach_to_current:
            return None
        current_id = self._scene_network.resolve_current_scene_id(world_id)
        if current_id:
            return current_id
        for scene in self._scene_network.list_scenes(world_id):
            if "home" in scene.tags or scene.name.strip() in ("家", "home"):
                return scene.id
        scenes = self._scene_network.list_scenes(world_id)
        if scenes:
            return scenes[0].id
        return None

    def _resolve_anchor_from_draft_edges(
        self,
        world_id: str,
        edge_hints: tuple[str, ...],
    ) -> str | None:
        if not edge_hints:
            return None
        scenes = self._scene_network.list_scenes(world_id)
        for hint in edge_hints:
            text = hint.strip()
            if not text:
                continue
            for scene in scenes:
                if scene.id in text or scene.name.strip() in text:
                    return scene.id
        return None

    def _apply_node_mutations(
        self,
        world_id: str,
        mutations: tuple[SceneNodeMutation, ...],
    ) -> list[SceneGroundingTraceEntry]:
        entries: list[SceneGroundingTraceEntry] = []
        for idx, mutation in enumerate(mutations, start=1):
            scene = self._scene_network.get(mutation.scene_id)
            if scene is None or scene.world_id != world_id:
                entries.append(
                    SceneGroundingTraceEntry(
                        round=idx,
                        action="node_mutation_skipped",
                        observation=f"unknown scene_id={mutation.scene_id}",
                    )
                )
                continue
            cards = cards_from_meta(scene.meta)
            narrative = scene.narrative
            tags = list(scene.tags)
            action = mutation.action.strip()
            if action == "update_scene":
                if mutation.narrative.strip():
                    narrative = mutation.narrative.strip()
                if mutation.tags:
                    tags = list(mutation.tags)
                if mutation.cards:
                    cards = list(mutation.cards)
            elif action == "add_card":
                existing_ids = {card.id for card in cards}
                existing_titles = {card.title for card in cards}
                for card in mutation.cards:
                    if card.id in existing_ids or card.title in existing_titles:
                        continue
                    cards.append(card)
            elif action == "update_card":
                replacements = {card.id: card for card in mutation.cards if card.id}
                title_replacements = {card.title: card for card in mutation.cards if card.title}
                cards = [
                    replacements.get(card.id)
                    or title_replacements.get(card.title)
                    or card
                    for card in cards
                ]
            elif action == "remove_card":
                remove_ids = set(mutation.card_ids)
                cards = [card for card in cards if card.id not in remove_ids]
            else:
                entries.append(
                    SceneGroundingTraceEntry(
                        round=idx,
                        action="node_mutation_skipped",
                        observation=f"unsupported action={action}",
                    )
                )
                continue
            self._scene_network.upsert_scene(
                world_id,
                scene_id=scene.id,
                name=scene.name,
                narrative=narrative,
                location_id=scene.location_id,
                tags=tags,
                meta=cards_to_meta(cards),
            )
            entries.append(
                SceneGroundingTraceEntry(
                    round=idx,
                    action="node_mutation",
                    observation=(
                        f"{action} scene={scene.name}({scene.id}) "
                        f"reason={mutation.reason[:120]}"
                    ),
                )
            )
        return entries

    @staticmethod
    def blocked_result(reason: str) -> SceneGroundingResult:
        return SceneGroundingResult(
            scene_id="",
            scene_name="",
            blocked_reason=reason.strip(),
        )
