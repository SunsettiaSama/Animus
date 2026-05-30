from __future__ import annotations

from agent.soul.life.experience import LifeExperienceStack
from agent.soul.life.io.speak import LifeSpeakIO
from agent.soul.presence.service import PresenceService
from agent.soul.speak.io import SpeakDialogueBridge
from agent.soul.speak.io.outbound.life import SpeakLifeOutboundBridge
from agent.soul.speak.session import SpeakFeelingChunk, SpeakTurnChunk, resolve_feeling


def test_speak_bridge_records_via_experience_pipeline(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    pipeline = LifeExperienceStack(life_dir=life_dir)
    pipeline.bind_presence(presence)
    life_io = LifeSpeakIO(pipeline)

    bridge = SpeakDialogueBridge(life=SpeakLifeOutboundBridge(life_io))
    bridge.record_turn(
        SpeakTurnChunk(
            session_id="tao",
            user_text="快点",
            agent_text="好的，分三步",
            feeling=SpeakFeelingChunk(salience="这轮对我很重要", emotion="专注"),
        )
    )

    state = pipeline.dialogue.state("tao")
    assert state is not None
    assert len(state.session.turns) == 1
    turn = state.session.turns[0]
    assert turn.user_text == "快点"
    assert turn.agent_text == "好的，分三步"
    assert turn.salience == 0.7
    assert turn.emotion_label == "专注"

    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="ĺżŤçš",
        agent_text="ĺĽ˝çďźĺä¸ć­Ľ",
        salience=0.7,
        emotion_label="ä¸ćł¨",
    )
    from agent.soul.presence.transition import Expectation

    assert presence.snapshot("tao").expectation == Expectation.none


def test_pipeline_close_dialogue_ingests_interaction_unit(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    pipeline = LifeExperienceStack(life_dir=life_dir)

    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="ä˝ ĺĽ˝",
        agent_text="ĺ?,
        salience=0.3,
    )
    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="ččćść",
        agent_text="ĺĽ˝ç",
        salience=0.5,
        emotion_label="ä¸ćł¨",
    )
    from agent.soul.presence.share_desire import StaticStatePatch

    presence.patch_static(
        "tao",
        StaticStatePatch(
            affect="ä¸ćł¨",
            perception="ç¨ćˇĺ¨čćść",
            thinking="ćĺ¨çťçťĺç­",
        ),
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
            emotion="ä¸ćł¨",
            salience="čżč˝ŽĺŻšćĺžéčŚ?,
            valence="ĺżéć¸ć¸ĺŽĺż",
            arousal="ç˛žçĽĺžéä¸?,
        ),
    )
    resolved = resolve_feeling(chunk)
    assert resolved.emotion_label == "ä¸ćł¨"
    assert resolved.salience == 0.7
    assert resolved.valence_delta == 0.2
    assert resolved.arousal_delta == 0.2
