"""speak 沉睡/唤醒 + life 亲历事件通道（landmark→编剧材料）单测。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ── ① 沉睡/唤醒 ─────────────────────────────────────────────────────────────

def test_speak_service_dormant_until_started():
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.service import SpeakService
    from agent.soul.presence import PresenceService
    from infra.llm.llm import BaseLLM
    from unittest.mock import MagicMock
    from agent.soul.presence.share_desire import ShareDesire

    class _StubLLM(BaseLLM):
        def generate(self, prompt): return ""
        def stream_generate(self, prompt): yield ""
        def generate_messages(self, messages): return "好"
        def stream_generate_messages(self, messages): yield "好"

    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {
        "profile": {"name": "t", "built": True},
        "self_concept": {"narrative": "", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {"slices": {"general": "g", "dialogue": "d"}},
    }
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "平静"
    snap.state.somatic.render.return_value = "放松"
    snap.state.cognition.render.return_value = "清楚"
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.3
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.1
    presence.snapshot.return_value = snap

    class _Life:
        def touch_dialogue(self, sid): pass
        def emit_dialogue_turn(self, chunk): pass
        def record_turn_exchange(self, chunk): return MagicMock()

    svc = SpeakService(
        persona=persona,
        presence=PresenceService(),
        llm_engine=SpeakLLMEngine(_StubLLM()),
        life_outbound=_Life(),
        life_lifecycle=None,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
        typing_idle_ms=50,
    )
    # 沉睡：构造后未启动
    assert svc.started is False
    svc.start()
    assert svc.started is True
    svc.start()  # 幂等
    assert svc.started is True
    svc.stop()
    assert svc.started is False
    svc.stop()  # 未启动时 stop 为 no-op
    assert svc.started is False


# ── ② life 亲历事件通道 ─────────────────────────────────────────────────────

def _landmark(status: str, intention: str, at: datetime, narrative: str = ""):
    from agent.soul.life.virtual.journal.item import LandmarkStatus

    return SimpleNamespace(
        id=f"id-{intention}",
        intention=intention,
        scheduled_at=at.isoformat(),
        context="手账上下文",
        status=SimpleNamespace(value=status),
        narrative=narrative,
        is_due=lambda: False,
        mark_processing=lambda: None,
        mark_done=lambda *a, **k: None,
    )


class _StubJournal:
    def __init__(self, landmarks):
        self._items = landmarks

    def all_landmarks(self):
        return list(self._items)


class _StubVirtual:
    def __init__(self, journal):
        self.journal = journal


def test_current_landmark_briefs_phases():
    from agent.soul.life.manager import LifeManager

    now = datetime.now(timezone.utc)
    mgr = LifeManager.__new__(LifeManager)
    mgr._virtual = _StubVirtual(
        _StubJournal(
            [
                _landmark("processing", "在旧书市集摆摊", now - timedelta(minutes=10)),
                _landmark("pending", "夜访灯塔", now + timedelta(minutes=2)),
                _landmark("done", "整理标本盒", now - timedelta(minutes=30), narrative="她把标本按科属排好。"),
                _landmark("done", "上周的远足", now - timedelta(days=5), narrative="早就结束了。"),
                _landmark("pending", "明天的市集", now + timedelta(hours=3)),
            ]
        )
    )
    briefs = mgr.current_landmark_briefs(past_sec=3600.0, future_sec=300.0)
    phases = {b["intention"]: b["phase"] for b in briefs}
    assert phases["在旧书市集摆摊"] == "experiencing"
    assert phases["夜访灯塔"] == "due"
    assert phases["整理标本盒"] == "just_done"
    # 窗外的与未到点的不算
    assert "上周的远足" not in phases
    assert "明天的市集" not in phases
    done = next(b for b in briefs if b["phase"] == "just_done")
    assert "标本" in done["narrative"]


def test_current_landmark_briefs_empty_for_everyday():
    from agent.soul.life.manager import LifeManager

    mgr = LifeManager.__new__(LifeManager)
    mgr._virtual = _StubVirtual(_StubJournal([]))
    assert mgr.current_landmark_briefs() == []


def test_life_event_state_formatting_and_everyday():
    from agent.soul.speak.service import SpeakService

    svc = SpeakService.__new__(SpeakService)
    svc._life_event_port = lambda: [
        {"intention": "在旧书市集摆摊", "phase": "experiencing", "narrative": "摊位刚支起来"},
        {"intention": "整理标本盒", "phase": "just_done", "narrative": ""},
    ]
    state = svc._life_event_state()
    assert state["everyday"] is False
    assert any("正在经历" in line and "旧书市集" in line for line in state["events"])
    assert any("刚经历完" in line and "标本盒" in line for line in state["events"])

    svc._life_event_port = lambda: []
    state = svc._life_event_state()
    assert state == {"events": (), "everyday": True}

    svc._life_event_port = None
    assert svc._life_event_state() == {"events": (), "everyday": False}


def test_writing_materials_life_event_and_everyday_blocks():
    from agent.soul.speak.responders.request_driven.screenwriter.materials import (
        build_writing_materials,
    )

    clay = build_writing_materials(
        compose_meta={
            "life_event_briefs": ["[正在经历] 在旧书市集摆摊——摊位刚支起来"],
            "life_everyday": False,
        }
    )
    blocks = clay.render_clay_blocks()
    assert "角色亲历事件" in blocks
    assert "旧书市集" in blocks
    assert "只是日常" not in blocks

    clay = build_writing_materials(
        compose_meta={"life_event_briefs": [], "life_everyday": True}
    )
    blocks = clay.render_clay_blocks()
    assert "只是在过日常" in blocks
    assert "不要编造任务感" in blocks

    # 未提供 life 通道时（旧装配）：不渲染任何事件块
    clay = build_writing_materials(compose_meta={})
    assert "角色亲历事件" not in clay.render_clay_blocks()
    assert "只是在过日常" not in clay.render_clay_blocks()


def test_coordinator_compose_materials_injects_life_state():
    from agent.soul.speak.responders.request_driven.directors.coordinator import (
        DirectorCoordinator,
    )

    coord = DirectorCoordinator.__new__(DirectorCoordinator)
    coord._life_event_state_fn = lambda: {
        "events": ("[正在经历] 在旧书市集摆摊",),
        "everyday": False,
    }
    coord._landmark_briefs_fn = None
    coord._state_store = SimpleNamespace(
        session=lambda sid: SimpleNamespace(
            director_cache={},
            presence_card=SimpleNamespace(ready=False, mood="", brief=""),
            silence_log=SimpleNamespace(ready=False, entries=()),
            fate_speak_desire=None,
            fate_tendency="",
            notes=[],
        )
    )
    snapshot = SimpleNamespace(
        session_id="s1",
        orchestrator=SimpleNamespace(compose_meta={"persona_brief": "x"}),
    )
    meta = coord._compose_materials(snapshot)
    assert meta["life_event_briefs"] == ["[正在经历] 在旧书市集摆摊"]
    assert meta["life_everyday"] is False
