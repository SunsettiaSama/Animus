"""Unit tests for Speak→Worker intent matcher and state machine."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from worker.work.matcher import WorkIntentMatcher
from worker.work.service import WorkerWorkService
from worker.work.types import ALLOWED_TRANSITIONS, WorkStatus


def test_matcher_requires_you_and_verb():
    m = WorkIntentMatcher()
    assert m.match_text("今天聊聊这个设计").matched is False
    hit = m.match_text("你帮我整理一下 webui")
    assert hit.matched is True
    assert "你" in hit.matched_terms
    assert "帮" in hit.matched_terms or "整理" in hit.matched_terms


def test_matcher_build_signal():
    m = WorkIntentMatcher()
    sig = m.build_signal(
        "你帮我改一下路由",
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
    )
    assert sig is not None
    assert sig.session_id == "s1"
    assert sig.question.startswith("你帮我")


def test_allowed_transitions_minimal():
    assert WorkStatus.pending_confirmation in ALLOWED_TRANSITIONS[WorkStatus.detected]
    assert WorkStatus.starting in ALLOWED_TRANSITIONS[WorkStatus.pending_confirmation]
    assert WorkStatus.running in ALLOWED_TRANSITIONS[WorkStatus.starting]
    assert WorkStatus.finished in ALLOWED_TRANSITIONS[WorkStatus.running]
    assert WorkStatus.running not in ALLOWED_TRANSITIONS[WorkStatus.finished]


def test_service_ask_confirmation_and_decline_fallback():
    events: list[dict] = []
    svc = WorkerWorkService(llm_cfg_path="config/llm_core/config.yaml", confirmation_timeout_sec=30)
    svc.set_default_sink(events.append)

    sig = svc.maybe_signal(
        "你帮我整理一下 webui 模块",
        session_id="sess-a",
        channel_id="chan-a",
        gen_id="gen-a",
    )
    assert sig is not None
    decision = svc.submit_intent(sig)
    assert decision.decision == "needs_work"
    assert decision.requires_user_confirmation is True
    types = [e["type"] for e in events]
    assert "work_intent_detected" in types
    assert "work_confirmation_required" in types

    events.clear()
    result = svc.handle_confirmation(sig.work_id, approved=False, reason="用户拒绝执行")
    assert result["fallback_to_speak"] is True
    types = [e["type"] for e in events]
    assert "work_declined" in types
    assert "work_fallback_to_speak" in types


def test_service_auto_decline_short():
    events: list[dict] = []
    svc = WorkerWorkService(llm_cfg_path="config/llm_core/config.yaml")
    svc.set_default_sink(events.append)
    sig = svc.maybe_signal(
        "你写",
        session_id="s",
        channel_id="c",
        gen_id="g",
    )
    assert sig is not None
    decision = svc.submit_intent(sig)
    assert decision.decision == "insufficient"
    assert decision.fallback_to_speak is True
    assert any(e["type"] == "work_declined" for e in events)
    assert any(e["type"] == "work_fallback_to_speak" for e in events)
