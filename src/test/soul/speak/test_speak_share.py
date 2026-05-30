from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.compose import ShareDesireComposer, SpeakPromptComposer
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue


def test_share_reveal_by_index_returns_full_text():
    snap = MagicMock()
    snap.state.expectation.to_dict.return_value = {
        "share_queue": ShareIntentQueue(
            items=[
                ShareIntent(
                    topic="今天的架构进�?,
                    share_desire=ShareDesire.moderate,
                    source="life_sync",
                    salience=0.72,
                ),
            ],
        ).to_dict(),
    }
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.moderate

    composer = ShareDesireComposer()
    result = composer.reveal(snap, "0", trigger_source="test")
    assert result.ok is True
    assert "今天的架构进�? in result.full_text
    assert "life_sync" in result.full_text
    assert result.trigger_source == "test"


def test_share_reveal_unknown_pointer():
    snap = MagicMock()
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none

    result = ShareDesireComposer().reveal(snap, "9")
    assert result.ok is False


def test_prompt_composer_exposes_reveal_share():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {"profile": {"name": "A"}, "self_concept": {}}
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {
        "share_queue": ShareIntentQueue(
            items=[ShareIntent(topic="想聊聊天�?, share_desire=ShareDesire.mild)],
        ).to_dict(),
    }
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.mild
    presence.snapshot.return_value = snap

    composer = SpeakPromptComposer(persona, presence)
    revealed = composer.reveal_share("tao", "0", trigger_source="reserved")
    assert revealed.ok is True
    assert "想聊聊天�? in revealed.full_text


def test_pop_share_handoff_uses_presence_pop():
    presence = MagicMock()
    intent = ShareIntent(
        topic="今天的架构进�?,
        share_desire=ShareDesire.moderate,
        source="life_sync",
        salience=0.88,
    )
    presence.pop_share_intent.return_value = intent

    result = ShareDesireComposer().pop_handoff(presence, "tao")
    presence.pop_share_intent.assert_called_once_with("tao")
    assert result.ok is True
    assert "今天的架构进�? in result.full_text
    assert result.trigger_source == "state:share"


def test_run_turn_share_state_pops_and_regenerates():
    call_count = {"n": 0}

    class _LLM:
        def generate_messages(self, messages):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "[think]准备分享[/think][state]share[/state]"
            system = messages[0].content
            assert "【分享详情�? in system
            assert "今天的架构进�? in system
            return "[think]说[/think][speak]今天架构有进展，值得聊聊。[/speak][state]finish[/state]"

        def stream_generate_messages(self, messages):
            text = self.generate_messages(messages)
            yield from text

    soul = MagicMock()
    soul.get_persona_snapshot.return_value = {
        "profile": {"name": "A"},
        "self_concept": {},
    }
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.0
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.0
    presence.snapshot.return_value = snap
    presence.pop_share_intent.return_value = ShareIntent(
        topic="今天的架构进�?,
        share_desire=ShareDesire.moderate,
        source="life_sync",
        salience=0.88,
    )

    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.service import SpeakService
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound

    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(_LLM()),
        composer=SpeakPromptComposer(soul, presence),
        life_outbound=RecordingSpeakLifeOutbound(),
        life_lifecycle=None,
    )
    result = service.run_turn("tao", "你好")
    assert call_count["n"] == 2
    presence.pop_share_intent.assert_called_once_with("tao")
    assert "架构有进�? in result.answer
    assert result.output is not None
    assert result.output.session_state == "finish"
    assert "session_state: share" in result.notes
    assert result.recorded is True
