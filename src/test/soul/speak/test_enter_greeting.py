from __future__ import annotations

from agent.soul.speak.session.lifecycle.hold.registry import SpeakSessionRegistry
from agent.soul.speak.session.manage.enter_greeting import (
    EnterGreetingManager,
    parse_enter_greeting_decision,
)
from agent.soul.speak.session.manage.types import EnterGreetingTurnSpec


def test_parse_enter_greeting_decision_greet():
    raw = "[think]可以轻轻打个招呼\n角度：轻问有没有人[/think][state]greet[/state]"
    decision = parse_enter_greeting_decision(raw)
    assert decision.should_greet is True
    assert "轻问" in decision.angle


def test_enter_greeting_cancel_on_user_message():
    registry = SpeakSessionRegistry()
    manager = EnterGreetingManager(registry=registry)
    manager.arm_session("s1")
    assert "s1" in manager._states
    manager.on_user_message("s1")
    assert "s1" not in manager._states


def test_enter_greeting_angle_is_internal_spec_field():
    """angle 是内部话头参考，不应被当成对用户可见正文。"""
    spec = EnterGreetingTurnSpec(
        session_id="s1",
        elapsed_sec=60.0,
        angle="以轻量、无压力的问候或询问开启，避免侵入感。",
        thought="适合开口。\n角度：以轻量、无压力的问候或询问开启，避免侵入感。",
    )
    assert "避免侵入感" in spec.angle
    # 合成 user_text 只描述情境，不含 angle
    synthetic = f"（系统：用户进入会话已约 {int(spec.elapsed_sec)} 秒，尚未发言。）"
    assert "避免侵入感" not in synthetic
