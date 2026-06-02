"""Session ? agent ?????????initiative ?? + silence_break ?????"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agent.soul.speak.orchestrator import SpeakPromptBundle
from agent.soul.speak.orchestrator.assemble import finish_turn_bundle
from agent.soul.speak.orchestrator.guidance.social import (
    INITIATIVE_PROMPT,
    render_silence_break_block,
)
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.session.manage.coordinator import SessionSocialManager
from agent.soul.speak.session.manage.initiative import TurnInitiativeManager
from agent.soul.speak.session.manage.silence_break import SilenceBreakManager
from agent.soul.speak.session.manage.types import SilenceBreakTurnSpec


class _BreakSilenceLLM:
    def generate_messages(self, messages):
        return (
            "[think]?????????????[/think]"
            "[state]break_silence[/state]"
        )


class _HoldSilenceLLM:
    def generate_messages(self, messages):
        return "[think]????[/think][state]hold[/state]"


def _registry_mock(*, generation: int = 1, turn_index: int = 3):
    registry = MagicMock()
    registry.get.return_value = MagicMock(generation=generation)
    registry.current_turn_index.return_value = turn_index
    return registry


def test_initiative_injects_hint_on_inbound_turn():
    initiative = TurnInitiativeManager(
        cooldown_turns=0,
        hint_probability=1.0,
        min_turn_index=0,
        max_user_chars=500,
    )
    initiative._rng = lambda: 0.0
    hint = initiative.evaluate("s1", turn_index=3, user_text="??", mode="inbound")
    assert hint is not None
    assert INITIATIVE_PROMPT in hint.text


def test_initiative_skipped_for_proactive_mode():
    initiative = TurnInitiativeManager(hint_probability=1.0, min_turn_index=0)
    initiative._rng = lambda: 0.0
    assert initiative.evaluate("s1", turn_index=5, user_text="hi", mode="proactive") is None


def test_finish_turn_bundle_injects_initiative_into_social_blocks():
    initiative = TurnInitiativeManager(
        cooldown_turns=0,
        hint_probability=1.0,
        min_turn_index=0,
    )
    initiative._rng = lambda: 0.0
    social = SessionSocialManager(registry=_registry_mock(), initiative=initiative)
    bundle = SpeakPromptBundle(session_id="s1")
    finish_turn_bundle(
        bundle,
        social=social,
        session_id="s1",
        turn_index=4,
        user_text="????",
        mode="inbound",
    )
    assert any(INITIATIVE_PROMPT in block for block in bundle.guidance.social_blocks)
    assert any("initiative:" in note for note in bundle.notes)


def test_finish_turn_bundle_prefers_silence_break_over_initiative():
    initiative = TurnInitiativeManager(
        cooldown_turns=0,
        hint_probability=1.0,
        min_turn_index=0,
    )
    initiative._rng = lambda: 0.0
    social = SessionSocialManager(registry=_registry_mock(), initiative=initiative)
    spec = SilenceBreakTurnSpec(
        session_id="s1",
        elapsed_sec=95.0,
        angle="?????",
        thought="??????",
    )
    social.arm_silence_break(spec)
    bundle = SpeakPromptBundle(session_id="s1")
    finish_turn_bundle(
        bundle,
        social=social,
        session_id="s1",
        turn_index=4,
        user_text="????",
        mode="inbound",
    )
    assert bundle.meta.get("silence_break") is True
    assert bundle.meta.get("silence_break_user")
    assert any("????" in block for block in bundle.guidance.social_blocks)
    assert not any(INITIATIVE_PROMPT in block for block in bundle.guidance.social_blocks)


def test_silence_break_timer_invokes_handler_when_llm_accepts():
    handled: list[SilenceBreakTurnSpec] = []
    mgr = SilenceBreakManager(
        registry=_registry_mock(),
        silence_sec=10.0,
        base_probability=1.0,
    )
    mgr.is_active = lambda _sid: True
    mgr.is_pushing = lambda _sid: False
    mgr.set_break_handler(lambda spec: handled.append(spec))
    mgr.set_llm(SpeakLLMEngine(_BreakSilenceLLM()))
    mgr.start_worker()

    past = datetime.now(timezone.utc) - timedelta(seconds=120)
    state = mgr._state("tao")
    state.last_agent_at = past
    state.last_user_at = past

    mgr._on_timer("tao")
    mgr.stop_worker()

    assert len(handled) == 1
    assert handled[0].session_id == "tao"
    assert "????" in render_silence_break_block(handled[0])


def test_silence_break_skips_when_llm_holds():
    handled: list[SilenceBreakTurnSpec] = []
    mgr = SilenceBreakManager(
        registry=_registry_mock(),
        silence_sec=10.0,
        base_probability=1.0,
    )
    mgr.is_active = lambda _sid: True
    mgr.is_pushing = lambda _sid: False
    mgr.set_break_handler(lambda spec: handled.append(spec))
    mgr.set_llm(SpeakLLMEngine(_HoldSilenceLLM()))
    mgr.start_worker()

    past = datetime.now(timezone.utc) - timedelta(seconds=120)
    state = mgr._state("tao")
    state.last_agent_at = past
    state.last_user_at = past

    mgr._on_timer("tao")
    mgr.stop_worker()

    assert handled == []


def test_speak_service_wires_silence_break_handler():
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound
    from agent.soul.speak.service import SpeakService

    service = SpeakService(
        persona=MagicMock(),
        presence=MagicMock(),
        life_outbound=RecordingSpeakLifeOutbound(),
    )
    handler = service._session_manager.social.silence._handler
    assert handler is not None
    assert handler.__name__ == "_execute_silence_break"


def test_on_turn_complete_schedules_silence_only_after_inbound_finish():
    registry = _registry_mock()
    social = SessionSocialManager(registry=registry)
    fired: list[str] = []

    class _Spy(SilenceBreakManager):
        def _schedule_timer(self, session_id: str, state) -> None:
            fired.append(session_id)

    social.silence = _Spy(registry=registry)
    social.on_turn_complete("tao", mode="proactive", session_state="finish", answer="hi")
    assert fired == []
    social.on_turn_complete("tao", mode="inbound", session_state="append", answer="hi")
    assert fired == []
    social.on_turn_complete("tao", mode="inbound", session_state="finish", answer="??")
    assert fired == ["tao"]
