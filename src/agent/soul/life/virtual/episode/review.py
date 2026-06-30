from __future__ import annotations

import re

from agent.soul.life.experience.domain.episode import (
    EpisodeItemType,
    LandmarkEpisode,
    TypedMemoryItemDraft,
)

_SUBJECTIVE_MARKERS = re.compile(
    r"(觉得|感到|疼痛|痛|酸|麻|冷|热|凉意|指尖|膝|呼吸|懊恼|怀疑|犹豫|担心|不安|松了|紧张|后悔|判断|归因|心里)"
)
_OBSERVATION_FORBIDDEN = re.compile(
    r"(我觉得|我感到|我怀疑|我认为|大概|也许|可能|应当|下次)"
)


def review_episode_items(
    episode: LandmarkEpisode,
    items: list[TypedMemoryItemDraft],
) -> tuple[list[TypedMemoryItemDraft], list[TypedMemoryItemDraft]]:
    accepted: list[TypedMemoryItemDraft] = []
    rejected: list[TypedMemoryItemDraft] = []
    step_ids = {step.step_index for step in episode.arc_steps}
    for item in items:
        reason = _review_item(episode, item, step_ids)
        if reason:
            rejected.append(
                TypedMemoryItemDraft(
                    item_id=item.item_id,
                    item_type=item.item_type,
                    text=item.text,
                    focus=item.focus,
                    step_index=item.step_index,
                    scene_id=item.scene_id,
                    is_hypothesis=item.is_hypothesis,
                    source_arc_step=item.source_arc_step,
                    rejection_reason=reason,
                )
            )
            continue
        accepted.append(item)
    return accepted, rejected


def _review_item(
    episode: LandmarkEpisode,
    item: TypedMemoryItemDraft,
    step_ids: set[int],
) -> str:
    text = item.text.strip()
    if not text:
        return "空文本"
    if item.item_type == EpisodeItemType.episode:
        if len(text) < 12:
            return "episode 过短，不足以概括完整经历"
        if _looks_like_lesson(text) and len(text) < 40:
            return "episode 不能只是单条教训或事实"
        return ""
    if item.item_type == EpisodeItemType.arc_step:
        if item.source_arc_step not in step_ids and item.step_index not in step_ids:
            return "arc_step 无法对应 GM 弧拍"
        if not text:
            return "arc_step 缺少行动与裁定"
        return ""
    if item.item_type == EpisodeItemType.observation:
        if _SUBJECTIVE_MARKERS.search(text):
            return "observation 含主观推断"
        if _OBSERVATION_FORBIDDEN.search(text):
            return "observation 含推断或建议语气"
        return ""
    if item.item_type == EpisodeItemType.subjective_reaction:
        if not _SUBJECTIVE_MARKERS.search(text) and "你" not in text:
            return "subjective_reaction 缺少身体感受/情绪/判断"
        return ""
    if item.item_type == EpisodeItemType.lesson_or_hypothesis:
        if item.is_hypothesis and _asserts_fact(text):
            return "hypothesis 被写成确定事实"
        if not item.is_hypothesis and not _traceable_to_observation(episode, item):
            return "lesson 缺少 observation 证据链"
        return ""
    return "未知 item 类型"


def _looks_like_lesson(text: str) -> bool:
    return bool(re.search(r"(下次|应当|需要|教训|经验)", text))


def _asserts_fact(text: str) -> bool:
    return bool(re.search(r"(确实|证实|已经|必然|一定)", text))


def _traceable_to_observation(episode: LandmarkEpisode, item: TypedMemoryItemDraft) -> bool:
    if item.source_arc_step <= 0:
        return True
    for step in episode.arc_steps:
        if step.step_index != item.source_arc_step:
            continue
        if step.objective_result.strip():
            return True
    return False


def compatible_subgraph_link(
    left: LandmarkEpisode,
    right: LandmarkEpisode,
    *,
    left_item: TypedMemoryItemDraft | None = None,
    right_item: TypedMemoryItemDraft | None = None,
) -> bool:
    if left.scene_id and right.scene_id and left.scene_id == right.scene_id:
        return True
    if left_item and right_item:
        if left_item.item_type == right_item.item_type == EpisodeItemType.lesson_or_hypothesis:
            return _shared_tokens(left_item.text, right_item.text) >= 2
    return _shared_tokens(left.summary_text(), right.summary_text()) >= 3


def _shared_tokens(a: str, b: str) -> int:
    tokens_a = {token for token in re.findall(r"[\u4e00-\u9fff]{2,}", a) if len(token) >= 2}
    tokens_b = {token for token in re.findall(r"[\u4e00-\u9fff]{2,}", b) if len(token) >= 2}
    return len(tokens_a & tokens_b)
