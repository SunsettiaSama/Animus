from __future__ import annotations

from agent.soul.life.experience.domain.unit import ExperienceActionKind
from agent.soul.life.experience.domain.virtual_codec import (
    VirtualUnitContext,
    VirtualUnitTrigger,
    read_virtual_context,
)
from agent.soul.life.experience.ingest.builder import ExperienceBuilder
from agent.soul.life.virtual.narrative.engine import NarrativeEngine
from storyview.types import (
    GMAnswer,
    GMQuestion,
    ResolvedOutcome,
    ScenePacket,
    StoryBeatOutcome,
    StoryEventKind,
    StoryInfluence,
)


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.ingested = []

    def ingest(self, unit) -> None:
        self.ingested.append(unit)


class _FakeLLM:
    def __init__(self) -> None:
        self.last_prompt = ""

    def generate_messages(self, messages) -> str:
        self.last_prompt = str(messages[-1].content)
        return (
            "[NARRATIVE]\n"
            "你看见灯影在窗边轻轻晃动，脚步慢下来，心里先确认周围是否安全。"
            "这件事让你在短暂迟疑后更专注，也把余下的注意力留在那盏灯上。\n"
            "[/NARRATIVE]\n"
            "[PERCEPTION]\n你看见灯影轻晃。\n[/PERCEPTION]\n"
            "[EMOTION]\n你稍微安定下来。\n[/EMOTION]\n"
            "[INTENSITY]\n0.55\n[/INTENSITY]"
        )


def _sample_outcome() -> StoryBeatOutcome:
    question = GMQuestion(
        question_id="q1",
        world_id="w1",
        kind=StoryEventKind.landmark,
        cue="观察灯",
        scene_id="scene-home",
        question="你打算怎么做？",
    )
    answer = GMAnswer(question_id="q1", text="你走近灯。", intent="走近")
    packet = ScenePacket(
        event_id="evt-1",
        world_id="w1",
        scene_text="客观场景文本",
    )
    resolved = ResolvedOutcome(
        event_id="evt-1",
        world_id="w1",
        resolution_text="客观结果文本",
        dice_value=55,
        dice_tendency="大体如预期",
    )
    return StoryBeatOutcome(
        question=question,
        answer=answer,
        scene_packet=packet,
        resolved=resolved,
        dice_value=55,
        dice_tendency="大体如预期",
        influence=StoryInfluence(salience=0.6),
    )


def test_record_virtual_beat_splits_fields():
    orch = _FakeOrchestrator()
    builder = ExperienceBuilder(orch)
    ctx = VirtualUnitContext(
        trigger=VirtualUnitTrigger.landmark,
        landmark_id="lm-1",
        dice_value=55,
        dice_tendency="大体如预期",
        story_event_id="evt-1",
        scene_id="scene-home",
        question_id="q1",
    )
    unit = builder.record_virtual_beat(
        "主观叙事正文",
        perception="你看见灯影晃动。",
        action_summary="走近灯",
        emotion_text="你稍定下来。",
        emotion_label="明显触动",
        salience=0.6,
        action_kind=ExperienceActionKind.deciding,
        virtual_ctx=ctx,
    )
    assert unit.situation.narration == "主观叙事正文"
    assert unit.situation.perception == "你看见灯影晃动。"
    assert unit.action.content == "走近灯"
    assert unit.feeling.emotion_label == "明显触动"
    restored = read_virtual_context(unit)
    assert restored is not None
    assert restored.story_event_id == "evt-1"
    assert restored.scene_id == "scene-home"
    assert restored.question_id == "q1"


def test_outcome_fields_available_for_life():
    outcome = _sample_outcome()
    assert outcome.scene_packet.scene_text == "客观场景文本"
    assert outcome.resolved.resolution_text == "客观结果文本"
    assert outcome.question.question
    assert outcome.answer.text


def test_subjective_from_outcome_hides_dice_from_prompt():
    llm = _FakeLLM()
    engine = NarrativeEngine(llm)
    draft = engine.subjective_from_outcome(
        objective_scene="客观场景文本",
        resolution_text="客观结果文本",
        gm_question="你打算怎么做？",
        soul_answer="你走近灯。",
        journal_intention="在雨后的庭院里观察一盏将熄未熄的灯",
        journal_context="雨后空气很静",
        profile_narrative="",
        continuity_memories=[],
        world_background="",
        default_intensity=0.55,
    )
    assert draft.narrative
    assert "命运骰" not in llm.last_prompt
    assert "d100" not in llm.last_prompt
    assert "大体如预期" not in llm.last_prompt
    assert "将熄未熄的灯" in llm.last_prompt
    assert "雨后空气很静" in llm.last_prompt
