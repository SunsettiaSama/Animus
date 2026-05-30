from __future__ import annotations

from agent.soul.speak.session.lifecycle.hold.registry import SpeakSessionRegistry
from agent.soul.speak.session.manage.enter_greeting import (
    EnterGreetingManager,
    parse_enter_greeting_decision,
)


def test_parse_enter_greeting_decision_greet():
    raw = "[think]可以轻轻打个招呼[/think][state]greet[/state]"
    decision = parse_enter_greeting_decision(raw)
    assert decision.should_greet is True


def test_enter_greeting_cancel_on_user_message():
    registry = SpeakSessionRegistry()
    manager = EnterGreetingManager(registry=registry)
    manager.arm_session("s1")
    assert "s1" in manager._states
    manager.on_user_message("s1")
    assert "s1" not in manager._states
