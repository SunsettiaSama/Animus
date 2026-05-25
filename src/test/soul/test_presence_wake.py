from __future__ import annotations

import json

import pytest

from agent.soul.heartbeat.checklist.registry import default_checklist
from agent.soul.heartbeat.module import HeartbeatModule
from agent.soul.presence.actions import PresenceAction
from agent.soul.presence.transition import PresenceWakeEngine, WakeContext
from agent.soul.presence.fsm.state import PresenceState
from agent.soul.presence.service import PresenceService
from runtime.scheduler.heartbeat_config import HeartbeatConfig


class _WakeLLM:
    def generate_messages(self, messages, **kwargs) -> str:
        return json.dumps(
            {
                "affect": "醒来时心里平静，带着一点期待。",
                "somatic": "身体从休眠中苏醒，肩颈略僵但正在舒展。",
                "working_memory": "还记得要继续未完成的事。",
                "thinking": "先理清今天最想回应什么。",
                "perception": "周围很安静，像一间等待被点亮的工位。",
            },
            ensure_ascii=False,
        )


def test_wake_engine_writes_narratives():
    state = PresenceState()
    engine = PresenceWakeEngine(_WakeLLM())
    result = engine.wake(
        state,
        context=WakeContext(agent_name="小助", timezone="Asia/Shanghai"),
    )
    assert result.applied is True
    assert "平静" in state.affect.narrative
    assert state.cognition.working_memory
    assert state.perception.narrative


def test_presence_wake_and_sleep_lifecycle(soul_temp_dir):
    svc = PresenceService(
        life_dir=soul_temp_dir,
        wake_engine=PresenceWakeEngine(_WakeLLM()),
        timezone="Asia/Shanghai",
    )
    assert not svc.is_awake("tao")
    wake = svc.wake_up("tao", context=WakeContext(agent_name="小助", timezone="Asia/Shanghai"))
    assert wake.applied is True
    assert svc.is_awake("tao")
    assert svc.snapshot("tao").state.render()

    again = svc.wake_up("tao", context=WakeContext(timezone="Asia/Shanghai"))
    assert again.applied is False

    sleep = svc.sleep("tao")
    assert sleep.applied is True
    assert not svc.is_awake("tao")
    assert svc.snapshot("tao").state.is_empty()


def test_default_checklist_includes_presence_wake():
    items = default_checklist()
    wake_items = [i for i in items if i.action == PresenceAction.WAKE_UP]
    assert len(wake_items) == 1
    assert wake_items[0].daily_at == "08:00"


def test_heartbeat_skips_outside_active_hours_and_sleeps(soul_temp_dir):
    from config.soul.config import SoulConfig

    presence = PresenceService(
        life_dir=soul_temp_dir,
        wake_engine=PresenceWakeEngine(_WakeLLM()),
        timezone="Asia/Shanghai",
    )
    presence.wake_up("tao", context=WakeContext(agent_name="测试"), force=True)
    assert presence.is_awake()

    soul = type("SoulStub", (), {})()
    soul.is_running = True
    soul.presence = presence
    soul.config = SoulConfig()
    sleep_calls: list[str] = []

    def _sleep(session_id: str = "tao"):
        sleep_calls.append(session_id)
        return presence.sleep(session_id)

    soul.run_presence_sleep = _sleep
    soul.run_presence_wake = lambda session_id="tao", force=False: {"ok": True}

    hb = HeartbeatModule(
        cfg=HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00"),
        scheduler_dir=soul_temp_dir,
        llm_cfg_path="config/llm_core/config.yaml",
    )
    hb._soul = soul
    hb._in_active_hours = lambda: False

    result = hb.tick()
    assert result.outcome == "skip"
    assert "sleeping" in result.reason
    assert sleep_calls == ["tao"]
    assert not presence.is_awake()


def test_heartbeat_tick_boundary_wake_and_sleep():
    from config.soul.config import SoulConfig
    from unittest.mock import MagicMock

    presence = PresenceService(
        wake_engine=PresenceWakeEngine(_WakeLLM()),
        timezone="Asia/Shanghai",
    )
    presence.wake_up("tao", context=WakeContext(agent_name="测试"), force=True)

    soul = MagicMock()
    soul.is_running = True
    soul.presence = presence
    soul.config = SoulConfig()
    soul.run_presence_sleep.side_effect = lambda session_id="tao": presence.sleep(session_id)
    soul.run_presence_wake.side_effect = lambda session_id="tao", force=False: presence.wake_up(
        session_id, context=WakeContext(agent_name="测试"), force=force
    )

    hb = HeartbeatModule(
        cfg=HeartbeatConfig(active_hours_start="08:00", active_hours_end="22:00"),
        scheduler_dir=".",
        llm_cfg_path="config/llm_core/config.yaml",
    )
    hb._soul = soul
    hb._in_active_hours = lambda: False
    skip = hb.tick()
    assert skip.outcome == "skip"
    soul.run_presence_sleep.assert_called_once()

    soul.run_presence_sleep.reset_mock()
    hb._in_active_hours = lambda: True
    presence.sleep("tao")
    assert not presence.is_awake()
    hb.tick()
    soul.run_presence_wake.assert_called_once()
