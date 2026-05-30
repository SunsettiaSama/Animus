from agent.soul.memory.graph.node.create.compression import build_unit_from_authoring
from agent.soul.memory.graph.node.create.experience import parse_experience_network
from agent.soul.memory.io.session import DialogueCompressionBlock


def test_build_unit_from_authoring_fields():
    block = DialogueCompressionBlock(
        session_id="sess-1",
        block_index=2,
        summary="蒸馏句",
        transcript="1. 用户：我是荧\n1. 我：记住了",
        salience=0.6,
        emotion_label="欣喜",
    )
    unit = build_unit_from_authoring(
        block,
        {
            "perception": "用户自报荧",
            "narration": "记下对方名字荧",
            "action_content": "热情回应并收好石子",
            "emotion_label": "欣喜",
            "valence": "positive",
            "salience": 0.7,
            "salience_note": "名字确认",
        },
        interactor_id="inter-1",
    )
    assert unit.situation.perception == "用户自报荧"
    assert unit.situation.narration == "记下对方名字荧"
    assert unit.action.content == "热情回应并收好石子"
    assert unit.feeling.salience == 0.7


def test_parse_network_routing():
    assert parse_experience_network("social").value == "anchor"
    assert parse_experience_network("event").value == "event"
    assert parse_experience_network("anchor").value == "anchor"
