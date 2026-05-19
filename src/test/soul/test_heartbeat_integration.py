from __future__ import annotations

from unittest.mock import patch

from agent.soul.heartbeat.module import HeartbeatModule
from runtime.scheduler.heartbeat_config import HeartbeatConfig


def test_bind_heartbeat_shares_orchestrator(soul_service, soul_temp_dir):
    soul_service.start()
    hb = HeartbeatModule(
        cfg=HeartbeatConfig(active_hours_start="", active_hours_end=""),
        scheduler_dir=soul_temp_dir,
        llm_cfg_path="config/llm_core/config.yaml",
        soul_config=soul_service.config,
    )
    hb.set_soul_service(soul_service)

    assert soul_service.orchestrator is hb.orchestrator
    assert soul_service._heartbeat is hb
    assert soul_service.status()["evolution_worker"]["state"] == "running"

    soul_service.stop()
    assert soul_service.orchestrator is None


def test_tick_skips_when_soul_not_running(soul_service, soul_temp_dir):
    hb = HeartbeatModule(
        cfg=HeartbeatConfig(active_hours_start="", active_hours_end=""),
        scheduler_dir=soul_temp_dir,
        llm_cfg_path="config/llm_core/config.yaml",
        soul_config=soul_service.config,
    )
    hb.set_soul_service(soul_service)

    result = hb.tick()
    assert result.outcome == "skip"
    assert result.reason == "soul not running"


def test_tick_runs_when_soul_running(soul_service, soul_temp_dir):
    soul_service.start()
    hb = HeartbeatModule(
        cfg=HeartbeatConfig(active_hours_start="", active_hours_end=""),
        scheduler_dir=soul_temp_dir,
        llm_cfg_path="config/llm_core/config.yaml",
        soul_config=soul_service.config,
    )
    hb.set_soul_service(soul_service)

    result = hb.tick()
    assert result.outcome == "ok"

    soul_service.stop()


def test_tao_config_accepts_subagent_memory_profile():
    """SubAgent profile 的 MemoryConfig 无 milestone 字段时不应阻断 TaoConfig 初始化。"""
    from agent.profile import SubAgentProfile
    from agent.soul.heartbeat.profiles import _sub_memory
    from config.agent.tao_config import TaoConfig

    TaoConfig(memory=_sub_memory())


def test_run_daily_reflection_builds_tao_request(soul_service):
    """日终反省至少能构造 Tao 请求；SubAgentRunner 由 mock 短路。"""
    from agent.soul.handlers.tao.actions import TaoPersonaAction
    from agent.soul.handlers.tao.types import TaoRunResult
    from agent.soul.request import SoulChannel, SoulDomain, SoulRequest

    soul_service.start()
    fake_result = {
        "answer": '{"thought_records":[],"reflective_note":""}',
        "step_count": 0,
        "steps_log": [],
        "steps": [],
    }

    with patch("agent.runner.SubAgentRunner.run_sync", return_value=fake_result):
        detail = soul_service.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=TaoPersonaAction.RUN_DAILY_REFLECTION,
            channel=SoulChannel.tao,
            payload={"today_dialogue": "无", "today_scheduler_tasks": "无"},
        ))

    assert detail["ok"] is True
    soul_service.stop()
