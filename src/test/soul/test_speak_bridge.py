from __future__ import annotations

from agent.soul.presence.experience.pipeline import PresenceExperiencePipeline
from agent.soul.presence.service import PresenceService
from agent.soul.speak.bridge import SpeakDialogueBridge
from agent.soul.speak.chunk import SpeakFeelingChunk, SpeakTurnChunk, resolve_feeling


def test_speak_bridge_records_via_experience_pipeline(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    pipeline = PresenceExperiencePipeline(life_dir=life_dir)
    recorded: list[dict] = []

    bridge = SpeakDialogueBridge(
        on_dialogue_turn=lambda **kwargs: recorded.append(kwargs),
    )
    bridge.record_turn(
        SpeakTurnChunk(
            session_id="tao",
            user_text="快点",
            agent_text="好的，分三步",
            feeling=SpeakFeelingChunk(salience="这轮对我很重要", emotion="专注"),
        )
    )

    assert recorded == [{
        "session_id": "tao",
        "user_text": "快点",
        "agent_text": "好的，分三步",
        "salience": 0.7,
        "emotion_label": "专注",
        "valence_delta": 0.0,
        "arousal_delta": 0.0,
        "activated_memory_ids": [],
        "proactive_intent_id": "",
    }]

    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="快点",
        agent_text="好的，分三步",
        salience=0.7,
        emotion_label="专注",
    )
    assert presence._dialogue_transition.block_count("tao") == 1


def test_pipeline_close_dialogue_ingests_interaction_unit(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    pipeline = PresenceExperiencePipeline(life_dir=life_dir)

    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="你好",
        agent_text="嗨",
        salience=0.3,
    )
    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="聊聊架构",
        agent_text="好的",
        salience=0.5,
        emotion_label="专注",
    )
    unit = pipeline.dialogue.close_dialogue(presence, "tao")
    assert unit is not None
    assert unit.source == "interaction"
    assert unit.situation.turn_index == 2
    hot = pipeline.log.recent()
    assert any(u.source == "interaction" for u in hot)


def test_resolve_feeling_from_text_notes():
    chunk = SpeakTurnChunk(
        session_id="tao",
        user_text="q",
        agent_text="a",
        feeling=SpeakFeelingChunk(
            emotion="专注",
            salience="这轮对我很重要",
            valence="心里渐渐安心",
            arousal="精神很集中",
        ),
    )
    resolved = resolve_feeling(chunk)
    assert resolved.emotion_label == "专注"
    assert resolved.salience == 0.7
    assert resolved.valence_delta == 0.2
    assert resolved.arousal_delta == 0.2
