from __future__ import annotations

import logging

from agent.soul.heartbeat.config import SoulHeartbeatConfig
from agent.soul.heartbeat.console_log import configure_console_log
from agent.soul.heartbeat.module import HeartbeatModule


def _open_hours_cfg() -> SoulHeartbeatConfig:
    return SoulHeartbeatConfig(
        active_hours_start="",
        active_hours_end="",
    )


def test_soul_start_owns_heartbeat(soul_service):
    soul_service.start()
    assert soul_service.heartbeat is not None
    assert soul_service.orchestrator is soul_service.heartbeat.orchestrator
    assert soul_service.status()["evolution_worker"]["state"] == "running"
    soul_service.stop()
    assert soul_service.heartbeat is None


def test_bind_heartbeat_override(soul_service, soul_temp_dir):
    hb = HeartbeatModule(
        cfg=_open_hours_cfg(),
        log_dir=soul_temp_dir,
        llm_cfg_path="config/llm_core/config.yaml",
        soul_config=soul_service.config,
    )
    soul_service.bind_heartbeat(hb)
    soul_service.start()

    assert soul_service.orchestrator is hb.orchestrator
    assert soul_service.heartbeat is hb

    soul_service.stop()


def test_console_log_disabled_suppresses_stdout(caplog, soul_temp_dir, soul_service):
    configure_console_log(True)
    caplog.set_level(logging.DEBUG)
    hb = HeartbeatModule(
        cfg=SoulHeartbeatConfig(
            active_hours_start="",
            active_hours_end="",
            console_log_enabled=False,
        ),
        log_dir=soul_temp_dir,
        llm_cfg_path="config/llm_core/config.yaml",
        soul_config=soul_service.config,
    )
    hb.set_soul_service(soul_service)
    hb.tick()
    assert not any("[Heartbeat]" in r.message for r in caplog.records)
    configure_console_log(True)


def test_tick_skips_when_soul_not_running(soul_service, soul_temp_dir):
    hb = HeartbeatModule(
        cfg=_open_hours_cfg(),
        log_dir=soul_temp_dir,
        llm_cfg_path="config/llm_core/config.yaml",
        soul_config=soul_service.config,
    )
    hb.set_soul_service(soul_service)

    result = hb.tick()
    assert result.outcome == "skip"
    assert result.reason == "soul not running"


def test_tick_runs_when_soul_running(soul_service):
    soul_service.start()
    soul_service.heartbeat.config.active_hours_start = ""
    soul_service.heartbeat.config.active_hours_end = ""

    result = soul_service.force_heartbeat_tick()
    assert result.outcome == "ok"

    soul_service.stop()


def test_tao_config_accepts_subagent_memory_profile():
    from agent.profile import SubAgentProfile
    from agent.soul.heartbeat.profiles import _sub_memory
    from config.agent.tao_config import TaoConfig

    TaoConfig(memory=_sub_memory())


def test_monthly_drift_stub(persona_cfg):
    from agent.soul.handlers.api.actions import PersonaAction
    from agent.soul.handlers.api.persona import PersonaHandler

    handler = PersonaHandler(persona_cfg)
    handler.service.manager.record_cluster_signals([{"theme": "????", "tick_id": "t1"}])
    detail = handler.handle(
        PersonaAction.RUN_MONTHLY_DRIFT,
        {"force": True},
    )

    assert detail["ok"] is True
    assert detail["applied"] is False
    assert detail["reason"] == "no_memory_port"
    assert detail["themes"] == ["????"]
