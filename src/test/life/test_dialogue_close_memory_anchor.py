from __future__ import annotations

from agent.soul.life.anchor.chronicle import AnchorChronicleKind, AnchorChronicleStore
from agent.soul.life.experience import LifeExperienceStack
from agent.soul.life.experience.anchor_codec import read_anchor_context
from agent.soul.presence.service import PresenceService
from agent.soul.presence.share_desire import StaticStatePatch
from agent.soul.presence.state import PresenceEvent


class _MemorySpy:
    def __init__(self) -> None:
        self.units: list = []

    def ingest_experience(self, unit) -> None:
        self.units.append(unit)

    def retract_experience(self, life_event_id: str) -> bool:
        _ = life_event_id
        return False


def test_close_dialogue_ingests_memory_and_anchor_chronicle(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    memory = _MemorySpy()
    anchor = AnchorChronicleStore(life_dir)
    stack = LifeExperienceStack(
        life_dir=life_dir,
        memory_port=memory,
        anchor_chronicle=anchor,
    )

    stack.dialogue.open_session("tao")
    presence.ingest(PresenceEvent.user_text("tao"))
    presence.patch_static(
        "tao",
        StaticStatePatch(
            perception="用户问了天气",
            thinking="我在组织回答",
            affect="有点开�?,
        ),
    )
    stack.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="今天天气怎样�?,
        agent_text="今天晴，适合出门�?,
        salience=0.5,
    )

    unit = stack.dialogue.close_dialogue(presence, "tao")
    assert unit is not None
    assert len(memory.units) == 1
    assert memory.units[0].source == "interaction"

    ctx = read_anchor_context(unit)
    assert ctx is not None
    assert ctx.session_id == "tao"

    entries = anchor.recent(5)
    assert any(e.kind == AnchorChronicleKind.interaction_close for e in entries)
