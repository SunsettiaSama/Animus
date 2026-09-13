"""出站只走一条链路：opening 不重推，flush_text 不进可见正文。"""

from __future__ import annotations

from agent.soul.speak.io.outbound.stream.parse.model import SpeakAgentOutput
from agent.soul.speak.responders.request_driven.character.contracts import (
    CharacterReplyRequest,
    CharacterReplyResult,
)
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    ReplySegment,
    build_delivery_plan,
)
from agent.soul.speak.responders.request_driven.timeline import RoleTimeline, TimelineOp
from agent.soul.speak.session.queue.user import UserInputItem
from test.soul.speak.test_director_single_character_request import _make_speak_service


def test_hot_reply_answer_not_polluted(monkeypatch):
    """热路径直达角色生成：决策层已删，正文不得再被决策 flush 文本污染。"""
    service = _make_speak_service()
    sid = "live:flush"
    paced = build_delivery_plan(
        segments=[ReplySegment(text="干活归干活", wait_ms=0, continuity="finish")],
        continuity="finish",
        plan_id="role",
        turn_index=1,
    )
    timeline = RoleTimeline(
        ops=(
            TimelineOp(kind="body", body="把最后一根竹篾按进纹路"),
            TimelineOp(kind="emit", texts=("干活归干活，眼睛总得有个落处。",)),
        )
    )

    class _Runtime:
        def run(self, *a, **k):
            del a, k
            return CharacterReplyResult(
                origin="user",
                trigger_id="t1",
                session_id=sid,
                turn_index=1,
                raw="<speak>干活归干活</speak>",
                answer_text="干活归干活，眼睛总得有个落处。",
                delivery_plan=paced,
                timeline=timeline,
                parsed=SpeakAgentOutput(speak="干活归干活，眼睛总得有个落处。"),
            )

    class _Mgr:
        def context_for_role(self, *a, **k):
            del a, k
            return object()

        def export_dynamic_materials(self, *a, **k):
            del a, k
            return DynamicLayerMaterials(session_id=sid)

    class _Gw:
        manager = _Mgr()

    service._character_runtime = _Runtime()
    service._compose_gateway = _Gw()
    service._compose_manager_materials = {}
    monkeypatch.setattr(
        service,
        "_director_dynamic_schedule",
        lambda *_a, **_k: DynamicLayerSchedule(reason="test"),
    )
    monkeypatch.setattr(service, "_finalize_character_reply", lambda *_a, **_k: [])

    answer, _parsed, out_paced, used, out_tl = service._run_user_hot_character_reply(
        request=CharacterReplyRequest(
            origin="user",
            session_id=sid,
            turn_index=1,
            trigger_id="t1",
            user_text="啊，看我干什么",
        ),
        bundle=SpeakPromptBundle(session_id=sid, mode="inbound"),
        notes=[],
        director_plan=paced,
    )
    assert used is True
    assert out_tl is timeline
    assert "要开口" not in answer
    assert "<body action>" not in answer
    assert "干活归干活" in answer
    assert all("要开口" not in (seg.text or "") for seg in out_paced.segments)
    assert all("<body action>" not in (seg.text or "") for seg in out_paced.segments)


def test_streamed_role_timeline_turn_finish_answer_empty(monkeypatch):
    service = _make_speak_service()
    sid = "live:dup"
    paced = build_delivery_plan(
        segments=[ReplySegment(text="干活归干活", wait_ms=0, continuity="finish")],
        continuity="finish",
        plan_id="role",
        turn_index=1,
    )
    timeline = RoleTimeline(
        ops=(
            TimelineOp(kind="body", body="搁下手头活"),
            TimelineOp(kind="emit", texts=("干活归干活",)),
        )
    )
    parsed = SpeakAgentOutput(speak="干活归干活")
    delivered: list[bool] = []

    monkeypatch.setattr(service, "_kick_for_upcoming_turn", lambda *a, **k: None)
    monkeypatch.setattr(service, "_refresh_compose_manager_director_meta", lambda *a, **k: None)
    monkeypatch.setattr(service, "notify_director_user_input", lambda *a, **k: None)
    monkeypatch.setattr(service, "_clear_async_delivery_ready", lambda *a, **k: None)
    monkeypatch.setattr(
        service,
        "_compose_bundle",
        lambda *a, **k: SpeakPromptBundle(session_id=sid, mode="inbound"),
    )
    monkeypatch.setattr(
        service,
        "_generate_request_driven_with_role_sidechain",
        lambda **k: ("干活归干活", parsed, paced, True, timeline),
    )
    monkeypatch.setattr(
        service,
        "_deliver_role_timeline",
        lambda *a, **k: delivered.append(bool(k.get("background"))) or [],
    )
    monkeypatch.setattr(service, "record_dialogue", lambda *a, **k: None)
    monkeypatch.setattr(service, "note_agent_visible_speak", lambda *a, **k: None)
    monkeypatch.setattr(service, "_on_compose_turn_complete", lambda *a, **k: None)
    monkeypatch.setattr(service._session_manager, "begin_turn", lambda *a, **k: None)
    monkeypatch.setattr(service._session_manager, "on_turn_complete", lambda *a, **k: None)
    monkeypatch.setattr(service, "session_trace_cache", lambda *a, **k: {})

    result = service._run_request_driven_turn(
        UserInputItem(
            session_id=sid,
            user_text="啊，看我干什么",
            stream=True,
            record=True,
            mode="inbound",
        )
    )
    assert result.answer == ""
    assert delivered == [True]


def test_narrative_outline_same_text_not_redelivered(monkeypatch):
    service = _make_speak_service()
    sid = "live:open"
    sent: list[str] = []
    monkeypatch.setattr(service, "_has_live_stream_session", lambda *_a, **_k: True)
    monkeypatch.setattr(
        service,
        "_execute_outbound_request",
        lambda *a, **k: sent.append("outline") or [],
    )
    service._deliver_narrative_outline(sid, text="你站在废弃档案馆的走廊尽头。")
    service._deliver_narrative_outline(sid, text="你站在废弃档案馆的走廊尽头。")
    service._deliver_narrative_outline(
        sid,
        text="你站在废弃档案馆的走廊尽头。",
        upgrade=True,
    )
    assert sent == ["outline"]
