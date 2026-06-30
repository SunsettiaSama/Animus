from __future__ import annotations

import hashlib
import re
import uuid

from storyview.types import GMExchange, StoryBeatOutcome

from agent.soul.life.experience.domain.episode import (
    ArcStepEvidence,
    EpisodeItemType,
    LandmarkEpisode,
    TypedMemoryItemDraft,
)
from agent.soul.life.virtual.narrative.engine import NarrativeDraft


def _stable_item_id(*parts: str) -> str:
    token = "|".join(part.strip() for part in parts if part.strip())
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"ep-item-{digest}"


def build_landmark_episode(
    outcome: StoryBeatOutcome,
    *,
    landmark_id: str = "",
    intention: str = "",
    context: str = "",
    experience_id: str = "",
    scene_name: str = "",
    scene_cards: list[dict] | None = None,
    draft: NarrativeDraft | None = None,
) -> LandmarkEpisode:
    steps = _arc_step_evidence(outcome)
    scene_id = outcome.question.scene_id
    if steps and steps[0].scene_id:
        scene_id = steps[0].scene_id
    episode = LandmarkEpisode(
        episode_id=str(uuid.uuid4()),
        experience_id=experience_id,
        landmark_id=landmark_id,
        intention=intention,
        context=context,
        scene_id=scene_id,
        scene_name=scene_name,
        scene_text=outcome.scene_packet.scene_text,
        objective_summary=outcome.objective_summary or outcome.resolved.resolution_text,
        scene_cards=list(scene_cards or []),
        arc_steps=steps,
    )
    if draft is not None:
        episode.subjective_journal = draft.narrative.strip()
        if draft.perception.strip() and steps:
            steps[0].subjective_reaction = draft.perception.strip()
    return episode


def _arc_step_evidence(outcome: StoryBeatOutcome) -> list[ArcStepEvidence]:
    arc_steps = list(outcome.arc_steps)
    if not arc_steps:
        arc_steps = [
            GMExchange(
                question=outcome.question,
                answer=outcome.answer,
                scene_packet=outcome.scene_packet,
                resolved=outcome.resolved,
            )
        ]
    evidence: list[ArcStepEvidence] = []
    for idx, step in enumerate(arc_steps, start=1):
        dice_value = int(getattr(step, "dice_value", 0) or step.resolved.dice_value or 0)
        dice_tendency = str(
            getattr(step, "dice_tendency", "")
            or step.resolved.dice_tendency
            or ""
        )
        story_direction = str(getattr(step, "story_direction", "") or step.resolved.story_direction or "")
        decision_importance = str(getattr(step, "decision_importance", "") or "")
        evidence.append(
            ArcStepEvidence(
                step_index=idx,
                gm_question=step.question.question.strip(),
                soul_answer=step.answer.text.strip(),
                objective_result=step.resolved.resolution_text.strip(),
                scene_id=step.question.scene_id,
                scene_text=step.scene_packet.scene_text.strip(),
                dice_value=dice_value,
                dice_tendency=dice_tendency,
                story_direction=story_direction,
                decision_importance=decision_importance,
            )
        )
    return evidence


def attach_episode_memory_drafts(
    episode: LandmarkEpisode,
    *,
    llm=None,
) -> LandmarkEpisode:
    from agent.soul.life.virtual.episode.items import extract_typed_memory_items
    from agent.soul.life.virtual.episode.review import review_episode_items

    items = extract_typed_memory_items(episode, llm=llm)
    accepted, rejected = review_episode_items(episode, items)
    episode.typed_memory_items = accepted
    episode.rejected_items = rejected
    return episode


def heuristic_lessons(episode: LandmarkEpisode) -> list[tuple[int, str, bool]]:
    lessons: list[tuple[int, str, bool]] = []
    for step in episode.arc_steps:
        text = step.objective_result.strip()
        if not text:
            continue
        for sentence in re.split(r"[。！？；]", text):
            snippet = sentence.strip()
            if not snippet:
                continue
            if re.search(r"(下次|以后|应当|需要|留意|小心|怀疑|可能)", snippet):
                lessons.append(
                    (
                        step.step_index,
                        snippet[:160],
                        bool(re.search(r"(怀疑|可能|似乎|隐约|暗示)", snippet)),
                    )
                )
                break
    return lessons[:4]


def build_episode_summary_item(episode: LandmarkEpisode) -> TypedMemoryItemDraft:
    return TypedMemoryItemDraft(
        item_id=_stable_item_id(episode.episode_id, "episode", episode.summary_text()[:80]),
        item_type=EpisodeItemType.episode,
        text=episode.summary_text()[:240] or episode.intention[:240],
        focus=episode.intention[:12] or "地标经历",
        scene_id=episode.scene_id,
    )
