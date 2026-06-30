from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from storyview.types import (
    SceneCard,
    SceneDraft,
    SceneReviewPatch,
    SceneReviewResult,
    SceneReviewStatus,
)
from storyview.world.provider import WorldviewProvider

_INSPECT_SYSTEM = (
    "你是 storyview 世界观审查员。审查场景草案是否符合世界设定、是否突兀、"
    "是否与已有 scene network 冲突、是否具备可互动 cards。先根据世界观、canon、"
    "已有场景网络抽象 keyword_groups，再生成 3 个审查问题 review_questions；"
    "随后带着这 3 个问题逐项审查草案，输出 question_reviews。"
    "scene narrative 必须是客观固定场景描述，只写地点、固定物、可交互设施、环境边界；"
    "禁止第一人称、Soul/智能体行动、今天/昨天/明天的日程过程、日志规划、已核对/将要执行等经历叙述。"
    "输出 JSON：keyword_groups、review_questions、question_reviews、status、reason、patches、approved_draft。"
    "keyword_groups 为 3 组关键词，每组含 name/keywords/purpose。"
    "review_questions 必须正好 3 个，分别从世界观抽象而来，不要使用固定词表。"
    "question_reviews 为 3 个对象：question、verdict(pass|weak|fail)、reason、suggestion。"
    "若 3 个问题至少 2 个 pass，可 approved 并给出简单 suggestion；否则 revision_required。"
    "revision_required 时必须给出可执行的字段级 patches，不能只写笼统建议。"
    "patches 为 [{field,value,items}]；field 只能是 name/narrative/location_hint/tags/cards/edges/reasoning。"
    "cards 的 value 必须是严格 JSON 数组字符串，card 字段使用 conditions 表达中性使用条件；edges/tags 可用 items。"
    "approved_draft 仅在 approved 时给出完整草案。"
)

_SUBJECTIVE_SCENE_MARKERS = (
    "我",
    "我们",
    "智能体",
    "Soul",
    "soul",
    "今天",
    "昨天",
    "明天",
    "日志",
    "规划",
    "计划",
    "工作是",
    "装备清单",
    "核对过",
    "需要去",
    "将要",
    "正在",
    "已经",
    "按照",
)


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"inspector expected JSON object, got: {text[:200]}")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("inspector expected JSON object")
    return payload


def _violates_forbidden(text: str, forbidden: list[str]) -> str:
    lowered = text.lower()
    for rule in forbidden:
        token = rule.strip()
        if not token:
            continue
        if token.lower() in lowered:
            return token
    return ""


def _scene_narrative_marker(text: str) -> str:
    for marker in _SUBJECTIVE_SCENE_MARKERS:
        if marker in text:
            return marker
    return ""


def _apply_patches(draft: SceneDraft, patches: tuple[SceneReviewPatch, ...]) -> SceneDraft:
    name = draft.name
    narrative = draft.narrative
    location_hint = draft.location_hint
    tags = list(draft.tags)
    cards = list(draft.cards)
    edges = list(draft.edges)
    reasoning = draft.reasoning
    for patch in patches:
        field = patch.field.strip()
        if field == "name" and patch.value.strip():
            name = patch.value.strip()
        elif field == "narrative" and patch.value.strip():
            narrative = patch.value.strip()
        elif field == "location_hint" and patch.value.strip():
            location_hint = patch.value.strip()
        elif field == "tags" and patch.items:
            tags = list(patch.items)
        elif field == "cards" and patch.value.strip():
            payload = json.loads(patch.value)
            if isinstance(payload, list):
                cards = [
                    SceneCard.from_dict(item)
                    for item in payload
                    if isinstance(item, dict)
                ]
        elif field == "edges" and patch.items:
            edges = list(patch.items)
        elif field == "reasoning" and patch.value.strip():
            reasoning = patch.value.strip()
    return SceneDraft(
        name=name,
        narrative=narrative,
        location_hint=location_hint,
        tags=tuple(tags),
        cards=tuple(cards),
        edges=tuple(edges),
        reasoning=reasoning,
    )


def _review_questions(payload: dict) -> tuple[str, ...]:
    raw = payload.get("review_questions") or []
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _question_reviews(payload: dict) -> tuple[dict, ...]:
    raw = payload.get("question_reviews") or []
    return tuple(item for item in raw if isinstance(item, dict))


def _review_verdict(entry: dict) -> str:
    return str(entry.get("verdict", "")).strip().lower()


def _review_gate(payload: dict) -> tuple[bool, str]:
    questions = _review_questions(payload)
    reviews = _question_reviews(payload)
    if len(questions) != 3 or len(reviews) != 3:
        return False, "worldview 审查必须先抽象 3 个 review_questions 并逐题给出 question_reviews"
    pass_count = sum(1 for entry in reviews if _review_verdict(entry) == "pass")
    lines = [f"worldview question pass={pass_count}/3"]
    for idx, entry in enumerate(reviews, start=1):
        question = str(entry.get("question", "")).strip() or questions[idx - 1]
        verdict = _review_verdict(entry) or "missing"
        reason = str(entry.get("reason", "")).strip()
        suggestion = str(entry.get("suggestion", "")).strip()
        line = f"Q{idx} {verdict}: {question}"
        if reason:
            line += f"；reason={reason}"
        if suggestion:
            line += f"；suggestion={suggestion}"
        lines.append(line)
    return pass_count >= 2, "\n".join(lines)


class WorldviewInspector:
    def __init__(
        self,
        provider: WorldviewProvider,
        *,
        llm=None,
    ) -> None:
        self._provider = provider
        self._llm = llm

    def review_scene_draft(
        self,
        world_id: str,
        cue: str,
        draft: SceneDraft,
        *,
        context: str = "",
    ) -> SceneReviewResult:
        rule_result = self._rule_review(world_id, draft)
        if rule_result.status == SceneReviewStatus.rejected:
            return rule_result
        if self._llm is None:
            if rule_result.status == SceneReviewStatus.revision_required:
                return rule_result
            return SceneReviewResult(
                status=SceneReviewStatus.approved,
                reason=rule_result.reason or "规则审查通过",
                approved_draft=draft,
            )
        prompt = (
            f"【世界观】\n{self._provider.render_worldview(world_id)}\n\n"
            f"【Canon】\n{json.dumps(self._provider.canon_rules(world_id), ensure_ascii=False)}\n\n"
            f"【已有上下文】\n{context or self._provider.existing_context(world_id)}\n\n"
            f"【Agenda cue】\n{cue.strip()}\n\n"
            f"【待审场景草案】\n{json.dumps(draft.to_dict(), ensure_ascii=False)}\n\n"
            f"【规则审查】\n{rule_result.reason}\n"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_INSPECT_SYSTEM), HumanMessage(content=prompt)]
        )
        payload = _extract_json(raw)
        gate_passed, gate_reason = _review_gate(payload)
        status = (
            SceneReviewStatus.approved
            if gate_passed
            else SceneReviewStatus.revision_required
        )
        patches_raw = payload.get("patches") or []
        patches = tuple(
            SceneReviewPatch.from_dict(item)
            for item in patches_raw
            if isinstance(item, dict)
        )
        approved_raw = payload.get("approved_draft")
        approved_draft = draft
        if isinstance(approved_raw, dict) and status == SceneReviewStatus.approved:
            approved_draft = SceneDraft.from_dict(approved_raw)
        elif patches:
            approved_draft = _apply_patches(draft, patches)
        if status == SceneReviewStatus.approved and len(approved_draft.cards) < 3:
            return SceneReviewResult(
                status=SceneReviewStatus.revision_required,
                reason="approved_draft 缺少足够 cards（至少 3 个）",
                patches=patches,
            )
        if status == SceneReviewStatus.approved:
            approved_rule_result = self._rule_review(world_id, approved_draft)
            if not approved_rule_result.is_approved:
                return SceneReviewResult(
                    status=approved_rule_result.status,
                    reason=approved_rule_result.reason,
                    patches=approved_rule_result.patches or patches,
                )
        return SceneReviewResult(
            status=status,
            reason="\n".join(
                item
                for item in (
                    str(payload.get("reason", "")).strip() or rule_result.reason,
                    gate_reason,
                )
                if item.strip()
            ),
            patches=patches if status != SceneReviewStatus.approved else (),
            approved_draft=approved_draft if status == SceneReviewStatus.approved else None,
        )

    def _rule_review(self, world_id: str, draft: SceneDraft) -> SceneReviewResult:
        if not draft.name.strip():
            return SceneReviewResult(
                status=SceneReviewStatus.revision_required,
                reason="缺少 scene name",
            )
        if not draft.narrative.strip():
            return SceneReviewResult(
                status=SceneReviewStatus.revision_required,
                reason="缺少 scene narrative",
            )
        marker = _scene_narrative_marker(draft.narrative)
        if marker:
            return SceneReviewResult(
                status=SceneReviewStatus.revision_required,
                reason=(
                    "scene narrative 含主观/日程叙述痕迹："
                    f"{marker}；请改为客观固定场景描述，只写地点、固定物、"
                    "可交互设施与环境边界。"
                ),
                patches=(
                    SceneReviewPatch(
                        field="narrative",
                        value=(
                            "改写为客观固定场景描述：描述场地形态、固定物件、"
                            "可交互设施、环境限制；不要写角色、智能体、今天/昨天/"
                            "明天、日志、计划或已发生动作。"
                        ),
                    ),
                ),
            )
        if len(draft.cards) < 3:
            return SceneReviewResult(
                status=SceneReviewStatus.revision_required,
                reason=f"cards 数量不足（{len(draft.cards)}，需要 3-6 个）",
            )
        if len(draft.cards) > 6:
            return SceneReviewResult(
                status=SceneReviewStatus.revision_required,
                reason=f"cards 过多（{len(draft.cards)}，最多 6 个）",
            )
        canon = self._provider.canon_rules(world_id)
        blob = " ".join(
            [
                draft.name,
                draft.narrative,
                " ".join(card.title for card in draft.cards),
                " ".join(card.description for card in draft.cards),
            ]
        )
        forbidden_hit = _violates_forbidden(blob, canon.get("forbidden") or [])
        if forbidden_hit:
            return SceneReviewResult(
                status=SceneReviewStatus.rejected,
                reason=f"违反 forbidden canon：{forbidden_hit}",
            )
        for card in draft.cards:
            if not card.title.strip() or not card.description.strip():
                return SceneReviewResult(
                    status=SceneReviewStatus.revision_required,
                    reason="存在缺少 title/description 的 card",
                )
        return SceneReviewResult(
            status=SceneReviewStatus.approved,
            reason="规则审查通过",
            approved_draft=draft,
        )
