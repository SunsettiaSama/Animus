"""用户→角色热路径优先于导演主动；导演不得制造空回 / 占用 turn_busy。"""

from __future__ import annotations

from agent.soul.speak.responders.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.session.queue.hub import SessionQueueHub
from agent.soul.speak.service import SpeakService, SpeakTurnResult


class _FakeLLM:
    def generate_messages(self, messages):
        del messages
        return "<speak>收到</speak>"

    def stream_generate_messages(self, messages):
        del messages
        yield "<speak>收到</speak>"


def test_director_handoff_does_not_set_turn_busy():
    """导演主动开口不得 begin_turn_busy，否则会阻塞用户角色接口。"""
    hub = SessionQueueHub()
    assert not hub.is_turn_busy("s1")
    assert not hub.is_busy("s1")
    # 仅用户 turn 才应占用
    hub.begin_turn_busy("s1")
    assert hub.is_turn_busy("s1")
    assert hub.is_busy("s1")
    hub.end_turn_busy("s1")
    assert not hub.is_busy("s1")


def test_user_submit_while_pushing_queues_interrupt_not_director_busy():
    hub = SessionQueueHub()
    hub.begin_push("s1", "director outbound")
    result = hub.submit_user_input(
        "s1",
        "在干啥呢，借我瞅瞅",
        stream=True,
        mode="inbound",
        record=True,
        responder="request_driven",
    )
    assert result.queued is True
    assert result.interrupt is True
    assert "director" in " ".join(result.notes).lower() or "character" in " ".join(
        result.notes
    ).lower()
    item = hub.pop_pending_user_input("s1")
    assert item is not None
    assert item.user_text == "在干啥呢，借我瞅瞅"
    assert item.interrupted is True


def test_run_turn_stamp_fallback_never_returns_empty_drain(monkeypatch):
    """queued 后队列抽干时，必须用 stamp 原文直达角色，禁止 user_input_drained 空回。"""
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound
    from unittest.mock import MagicMock

    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.0
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    presence.snapshot.return_value = snap

    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(_FakeLLM()),
        orchestrator=SpeakOrchestrator(soul, presence),
        life_outbound=RecordingSpeakLifeOutbound(),
        life_lifecycle=None,
    )

    calls: list[str] = []

    def _fake_process(session_id, *, initial=None):
        text = initial.user_text if initial is not None else ""
        calls.append(text)
        return SpeakTurnResult(
            session_id=session_id,
            answer=f"echo:{text}",
            bundle=SpeakPromptBundle(session_id=session_id, mode="inbound"),
            recorded=False,
            notes=["fake_process"],
            meta={},
        )

    monkeypatch.setattr(service, "_process_user_inputs", _fake_process)
    monkeypatch.setattr(service, "_wait_session_idle", lambda *_a, **_k: True)
    monkeypatch.setattr(service, "_drain_async_delivery_queue", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_flush_pending_character_handoff", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_kick_for_upcoming_turn", lambda *_a, **_k: None)

    # 模拟：submit 报 queued，但 wait 后队列已空（旧 drained 竞态）
    class _Submit:
        queued = True
        interrupt = True
        notes = ["session: user interrupt queued"]

    monkeypatch.setattr(
        service._session_manager,
        "submit_user_input",
        lambda *_a, **_k: _Submit(),
    )
    monkeypatch.setattr(
        service._session_manager.user_queue,
        "has_pending",
        lambda *_a, **_k: False,
    )

    result = service.run_turn("live:test", "在干啥呢，借我瞅瞅")
    assert "user_input_drained_by_active_turn" not in result.notes
    assert "user_direct_after_busy_stamp_fallback" in result.notes
    assert "never_empty_on_director_drain" in result.notes
    assert result.answer == "echo:在干啥呢，借我瞅瞅"
    assert calls == ["在干啥呢，借我瞅瞅"]


def test_run_turn_queued_does_not_wait_for_outbound_idle(monkeypatch):
    """用户打断出站后必须立刻进角色，禁止 _wait_session_idle 空等。"""
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound
    from unittest.mock import MagicMock

    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.0
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    presence.snapshot.return_value = snap

    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(_FakeLLM()),
        orchestrator=SpeakOrchestrator(soul, presence),
        life_outbound=RecordingSpeakLifeOutbound(),
        life_lifecycle=None,
    )
    waits: list[str] = []
    ended: list[str] = []

    def _fake_process(session_id, *, initial=None):
        text = initial.user_text if initial is not None else "from-queue"
        return SpeakTurnResult(
            session_id=session_id,
            answer=f"echo:{text}",
            bundle=SpeakPromptBundle(session_id=session_id, mode="inbound"),
            recorded=False,
            notes=["fake_process"],
            meta={},
        )

    monkeypatch.setattr(service, "_process_user_inputs", _fake_process)
    monkeypatch.setattr(
        service,
        "_wait_session_idle",
        lambda *_a, **_k: waits.append("waited") or True,
    )
    monkeypatch.setattr(service, "_drain_async_delivery_queue", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_flush_pending_character_handoff", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_kick_for_upcoming_turn", lambda *_a, **_k: None)
    monkeypatch.setattr(service._session_manager, "is_pushing", lambda *_a, **_k: True)
    monkeypatch.setattr(
        service._session_manager,
        "end_push",
        lambda sid, **_k: ended.append(sid),
    )

    class _Submit:
        queued = True
        interrupt = True
        notes = ["session: user interrupt queued"]

    monkeypatch.setattr(
        service._session_manager,
        "submit_user_input",
        lambda *_a, **_k: _Submit(),
    )
    monkeypatch.setattr(
        service._session_manager.user_queue,
        "has_pending",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        service._session_manager,
        "pop_pending_user_input",
        lambda *_a, **_k: None,
    )

    result = service.run_turn("live:block", "喂喂~听得到嘛")
    assert waits == []
    assert "live:block" in ended
    assert result.answer == "echo:from-queue"
    assert "user_direct_after_busy" in result.notes


def test_director_must_yield_when_user_turn_busy():
    from unittest.mock import MagicMock

    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound

    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.0
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    presence.snapshot.return_value = snap

    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(_FakeLLM()),
        orchestrator=SpeakOrchestrator(soul, presence),
        life_outbound=RecordingSpeakLifeOutbound(),
        life_lifecycle=None,
    )
    sid = "live:yield"
    assert service._director_must_yield_to_user(sid) is False
    service._session_manager.queues.begin_turn_busy(sid)
    assert service._director_must_yield_to_user(sid) is True
    service._session_manager.queues.end_turn_busy(sid)
    service._session_manager.queues.begin_push(sid, "outbound")
    service._session_manager.queues.submit_user_input(
        sid,
        "用户插话",
        stream=True,
        mode="inbound",
        record=True,
        responder="request_driven",
    )
    assert service._director_must_yield_to_user(sid) is True
