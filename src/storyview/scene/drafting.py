from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from storyview.types import SceneCard, SceneDraft, SceneUnit
from storyview.types import SceneReviewPatch
from storyview.world.provider import WorldviewProvider

_DRAFT_SYSTEM = (
    "你是 storyview 场景起草引擎。根据 agenda cue 生成 draft-only 场景，不得直接写入数据库。"
    "每轮只允许 action：inspect_worldview、inspect_existing_scene、revise_scene、finish。"
    "finish 时必须输出完整 scene draft，包含 3-6 个可互动 cards。"
    "cards 需有 id/title/description/affordances/conditions。"
    "conditions 是中性的使用条件/操作边界，优先描述如何使用、维护、校准、复核；"
    "不要把 conditions 写成大量禁止清单。"
    "scene narrative 必须是客观固定场景描述：只写地点、固定物、可交互设施、环境边界。"
    "禁止写第一人称、Soul/智能体行动、今天/昨天/明天的日程过程、日志规划、已核对/将要执行等经历叙述。"
    "不得超出 worldview/canon，不得凭空引入高冲突支线。"
)
_FINISH_SYSTEM = (
    "输出 JSON scene draft：name、narrative、location_hint、tags、cards、reasoning。"
    "cards 为 3-6 个对象，每个含 id/title/description/affordances/conditions/entities。"
    "conditions 使用中性措辞，表达使用条件、操作边界、维护条件或复核条件。"
    "narrative 只描述固定场景，不描述角色正在做、已经做、计划做什么。"
)


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"scene drafter expected JSON object, got: {text[:200]}")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("scene drafter expected JSON object")
    return payload


def _ensure_card_ids(cards: list[SceneCard]) -> list[SceneCard]:
    ensured: list[SceneCard] = []
    for card in cards:
        card_id = card.id.strip() or str(uuid.uuid4())
        ensured.append(
            SceneCard(
                id=card_id,
                title=card.title,
                description=card.description,
                affordances=card.affordances,
                conditions=card.conditions,
                entities=card.entities,
            )
        )
    return ensured


class SceneDraftingEngine:
    def __init__(
        self,
        provider: WorldviewProvider,
        *,
        llm=None,
        max_rounds: int = 6,
    ) -> None:
        self._provider = provider
        self._llm = llm
        self._max_rounds = max(1, max_rounds)

    def draft_for_cue(
        self,
        world_id: str,
        cue: str,
        *,
        existing_scenes: list[SceneUnit] | None = None,
        revision_reason: str = "",
        revision_patches: tuple[SceneReviewPatch, ...] = (),
        prior_draft: SceneDraft | None = None,
        allow_node_mutation: bool = False,
    ) -> SceneDraft:
        if self._llm is None:
            return self._fallback_draft(cue, prior_draft)
        scenes = existing_scenes or []
        state = prior_draft
        trace: list[str] = []
        for round_idx in range(1, self._max_rounds + 1):
            decision = self._decide(
                world_id,
                cue,
                scenes=scenes,
                state=state,
                trace=trace,
                revision_reason=revision_reason if round_idx == 1 else "",
                revision_patches=revision_patches if round_idx == 1 else (),
                allow_node_mutation=allow_node_mutation,
            )
            action = str(decision.get("action", "")).strip()
            if action == "finish":
                draft_payload = (
                    decision.get("draft")
                    or decision.get("output")
                    or decision.get("scene_draft")
                    or decision.get("approved_draft")
                )
                if isinstance(draft_payload, dict):
                    draft = SceneDraft.from_dict(draft_payload)
                elif state is not None:
                    draft = state
                else:
                    draft = self._fallback_draft(cue, prior_draft)
                draft = self._normalize_draft(
                    draft,
                    allow_node_mutation=allow_node_mutation,
                )
                return draft
            observation = self._run_action(
                world_id,
                action,
                cue=cue,
                scenes=scenes,
                query=str(decision.get("query", "")).strip(),
                allow_node_mutation=allow_node_mutation,
            )
            trace.append(f"R{round_idx}:{action}->{observation[:120]}")
            if action == "revise_scene":
                patch = decision.get("draft")
                if isinstance(patch, dict):
                    state = SceneDraft.from_dict(patch)
        if state is not None:
            draft = self._normalize_draft(
                state,
                allow_node_mutation=allow_node_mutation,
            )
            return SceneDraft(
                name=draft.name,
                narrative=draft.narrative,
                location_hint=draft.location_hint,
                tags=draft.tags,
                cards=draft.cards,
                edges=draft.edges,
                reasoning="llm_unfinished",
            )
        draft = self._fallback_draft(cue, prior_draft)
        return SceneDraft(
            name=draft.name,
            narrative=draft.narrative,
            location_hint=draft.location_hint,
            tags=draft.tags,
            cards=draft.cards,
            edges=draft.edges,
            reasoning="llm_unfinished",
        )

    def _decide(
        self,
        world_id: str,
        cue: str,
        *,
        scenes: list[SceneUnit],
        state: SceneDraft | None,
        trace: list[str],
        revision_reason: str,
        revision_patches: tuple[SceneReviewPatch, ...],
        allow_node_mutation: bool,
    ) -> dict:
        history = "\n".join(trace[-4:]) or "（首轮）"
        patches_text = json.dumps(
            [patch.to_dict() for patch in revision_patches],
            ensure_ascii=False,
        )
        mutation_policy = (
            "允许：你可以在 SceneDraft.node_mutations 中提出对已有节点的修改计划，"
            "仅限 update_scene/add_card/update_card/remove_card；必须提供 scene_id/action/reason。"
            if allow_node_mutation
            else "禁止：不要输出 node_mutations，不要修改已有节点/cards/描述，只能创建或修订当前 draft。"
        )
        prompt = (
            f"【Agenda cue】\n{cue.strip()}\n\n"
            f"【修订说明】\n{revision_reason.strip() or '（无）'}\n\n"
            f"【世界观审查补丁】\n{patches_text if revision_patches else '（无）'}\n\n"
            f"【节点修改权限】\n{mutation_policy}\n\n"
            f"【当前草案】\n"
            f"{json.dumps(state.to_dict(), ensure_ascii=False) if state else '（空）'}\n\n"
            f"【历史】\n{history}\n\n"
            "选择下一步 action 并输出 JSON。若存在审查补丁，必须优先按补丁修订；"
            "finish 时用 draft/output/scene_draft 字段返回完整 SceneDraft。"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_DRAFT_SYSTEM), HumanMessage(content=prompt)]
        )
        return _extract_json(raw)

    def _run_action(
        self,
        world_id: str,
        action: str,
        *,
        cue: str,
        scenes: list[SceneUnit],
        query: str,
        allow_node_mutation: bool,
    ) -> str:
        if action == "inspect_worldview":
            return self._provider.render_worldview(world_id)
        if action == "inspect_existing_scene":
            return self._provider.scene_network_context(
                world_id,
                query=query or cue,
                include_mutation_actions=allow_node_mutation,
            )
        if action == "revise_scene":
            return "请在本轮 revise_scene 的 draft 字段给出修订后的完整草案。"
        raise ValueError(f"unknown scene drafting action: {action}")

    def _normalize_draft(
        self,
        draft: SceneDraft,
        *,
        allow_node_mutation: bool = False,
    ) -> SceneDraft:
        cards = _ensure_card_ids(list(draft.cards))
        return SceneDraft(
            name=draft.name.strip() or "未命名场景",
            narrative=draft.narrative.strip(),
            location_hint=draft.location_hint.strip(),
            tags=tuple(tag.strip() for tag in draft.tags if tag.strip()),
            cards=tuple(cards),
            edges=draft.edges,
            node_mutations=draft.node_mutations if allow_node_mutation else (),
            reasoning=draft.reasoning.strip(),
        )

    def _fallback_draft(self, cue: str, prior: SceneDraft | None) -> SceneDraft:
        if prior is not None and prior.name.strip() and len(prior.cards) >= 3:
            return self._normalize_draft(prior)
        name = "工作场景"
        for token in ("书桌", "溪岸", "记录台", "观察点", "营地"):
            if token in cue:
                name = token
                break
        cards = [
            SceneCard(
                id=str(uuid.uuid4()),
                title="记录台",
                description="用于整理与核对记录的固定台面。",
                affordances=("整理记录", "核对标签"),
                conditions=("仅使用台面已有工具与记录材料",),
            ),
            SceneCard(
                id=str(uuid.uuid4()),
                title="样线标记",
                description="标定观察范围与采样位置的参考点。",
                affordances=("标记位置", "对照记录"),
                conditions=("沿已标定样线记录与复核",),
            ),
            SceneCard(
                id=str(uuid.uuid4()),
                title="安全观察点",
                description="可暂停并复核判断的固定位置。",
                affordances=("暂停观察", "复核清单"),
                conditions=("用于短暂停留、复核与整理观察结论",),
            ),
        ]
        return SceneDraft(
            name=name,
            narrative=f"{name}设有固定观察边界、记录位置与安全停留点，可用于持续记录与复核。",
            location_hint=name,
            tags=("agenda", "grounded"),
            cards=tuple(cards),
            reasoning="fallback draft",
        )
