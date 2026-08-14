from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.soul.speak.session.manage.initiative import TurnInitiativeManager
from agent.soul.speak.session.manage.proactive_window import ProactiveSessionWindowManager
from agent.soul.speak.session.manage.silence_break import (
    parse_silence_decision,
    render_silence_decision_user,
)
from agent.soul.speak.session.manage.types import SilenceBreakProbe


def test_initiative_skips_first_turn():
    mgr = TurnInitiativeManager(hint_probability=1.0, cooldown_turns=0)
    assert mgr.evaluate("s1", turn_index=1, user_text="你好") is None


def test_initiative_shows_after_cooldown():
    mgr = TurnInitiativeManager(hint_probability=1.0, cooldown_turns=1, min_turn_index=2)
    assert mgr.evaluate("s1", turn_index=2, user_text="继续") is not None
    assert mgr.evaluate("s1", turn_index=3, user_text="再说") is not None


def test_initiative_probability_uses_decay():
    mgr = TurnInitiativeManager(hint_probability=1.0, cooldown_turns=0, min_turn_index=0)
    mgr._rng = lambda: 0.6
    assert mgr.evaluate("s1", turn_index=2, user_text="continue", decay=0.5) is None


def test_initiative_skips_long_user_text():
    mgr = TurnInitiativeManager(hint_probability=1.0, max_user_chars=10)
    assert mgr.evaluate("s1", turn_index=3, user_text="x" * 20) is None


def test_parse_silence_decision_break():
    raw = "[think]对方可能在忙\n角度：轻问是否还在[/think][state]break_silence[/state]"
    decision = parse_silence_decision(raw)
    assert decision.should_break is True
    assert "忙" in decision.thought


def test_parse_silence_decision_hold():
    raw = "[think]不宜打扰[/think][state]hold[/state]"
    decision = parse_silence_decision(raw)
    assert decision.should_break is False


def test_render_silence_decision_user_includes_summary():
    probe = SilenceBreakProbe(
        session_id="s1",
        elapsed_sec=120.0,
        turn_index=4,
        dialogue_compressed="用户提到加班",
    )
    text = render_silence_decision_user(probe)
    assert "120" in text
    assert "加班" in text


def test_proactive_window_touch_resets_sqrt_decay():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def _now():
        return now

    mgr = ProactiveSessionWindowManager(timeout_sec=600.0, now_fn=_now)
    assert mgr.touch_user_message("s1") == 1.0
    now = now + timedelta(seconds=150)
    assert 0.88 < mgr.decay("s1") < 0.90
    mgr.touch_user_message("s1")
    assert mgr.decay("s1") == 1.0
    mgr.clear_all()
