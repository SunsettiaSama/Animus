from __future__ import annotations

from agent.soul.life.experience.domain.episode import EpisodeItemType
from agent.soul.life.virtual.episode.builder import build_landmark_episode
from agent.soul.life.virtual.episode.items import extract_typed_memory_items
from agent.soul.life.virtual.episode.review import review_episode_items
from storyview.types import (
    GMAnswer,
    GMExchange,
    GMQuestion,
    ResolvedOutcome,
    ScenePacket,
    StoryBeatOutcome,
    StoryEventKind,
    StoryInfluence,
)


def _sample_outcome() -> StoryBeatOutcome:
    question = GMQuestion(
        question_id="q1",
        world_id="w1",
        kind=StoryEventKind.landmark,
        cue="复核岩棚",
        scene_id="scene-rock-shelter",
        question="你先看哪里？",
    )
    answer = GMAnswer(question_id="q1", text="我先看湿度计。", intent="看湿度计")
    packet = ScenePacket(
        event_id="evt-1",
        world_id="w1",
        scene_text="岩棚内潮气更重，苔藓发暗。",
    )
    resolved = ResolvedOutcome(
        event_id="evt-1",
        world_id="w1",
        resolution_text="湿度读数偏高，裂隙标记偏转。",
        dice_value=42,
        dice_tendency="小有阻碍",
        story_direction="局面变紧",
    )
    step = GMExchange(
        question=question,
        answer=answer,
        scene_packet=packet,
        resolved=resolved,
        dice_value=42,
        dice_tendency="小有阻碍",
        story_direction="局面变紧",
        decision_importance="需要谨慎核对",
    )
    return StoryBeatOutcome(
        question=question,
        answer=answer,
        scene_packet=packet,
        resolved=resolved,
        dice_value=42,
        dice_tendency="小有阻碍",
        influence=StoryInfluence(salience=0.6, decision_importance="需要谨慎核对"),
        arc_steps=(step,),
        objective_summary="岩棚复核出现湿度异常与裂隙偏转。",
    )


def test_build_landmark_episode_keeps_scene_and_dice():
    episode = build_landmark_episode(
        _sample_outcome(),
        landmark_id="lm-1",
        intention="复核岩棚湿度",
        context="只在观察点内活动",
        scene_name="北坡风蚀岩棚观察点",
    )
    assert episode.scene_id == "scene-rock-shelter"
    assert len(episode.arc_steps) == 1
    assert episode.arc_steps[0].dice_value == 42
    assert episode.arc_steps[0].story_direction == "局面变紧"
    assert episode.arc_steps[0].decision_importance == "需要谨慎核对"


def test_extract_and_review_typed_items():
    episode = build_landmark_episode(
        _sample_outcome(),
        landmark_id="lm-1",
        intention="复核岩棚湿度",
    )
    items = extract_typed_memory_items(episode, llm=None)
    accepted, rejected = review_episode_items(episode, items)
    assert any(item.item_type == EpisodeItemType.episode for item in accepted)
    assert any(item.item_type == EpisodeItemType.arc_step for item in accepted)
    assert any(item.item_type == EpisodeItemType.observation for item in accepted)
    assert all(not item.rejection_reason for item in accepted)


def test_experience_unit_evidence_roundtrip():
    from agent.soul.life.experience.domain.unit import ExperienceUnit

    unit = ExperienceUnit.make(
        situation=__import__(
            "agent.soul.life.experience.domain.unit", fromlist=["ExperienceSituation"]
        ).ExperienceSituation(narration="test"),
        action=__import__(
            "agent.soul.life.experience.domain.unit", fromlist=["ExperienceAction", "ExperienceActionKind"]
        ).ExperienceAction(kind=__import__(
            "agent.soul.life.experience.domain.unit", fromlist=["ExperienceActionKind"]
        ).ExperienceActionKind.attending),
        feeling=__import__(
            "agent.soul.life.experience.domain.unit", fromlist=["ExperienceFeeling"]
        ).ExperienceFeeling(),
    )
    episode = build_landmark_episode(_sample_outcome(), landmark_id="lm-1", intention="复核")
    unit.evidence = {"landmark_episode": episode.to_dict()}
    restored = ExperienceUnit.from_dict(unit.to_dict())
    assert restored.evidence["landmark_episode"]["landmark_id"] == "lm-1"
