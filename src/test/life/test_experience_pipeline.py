from __future__ import annotations

from agent.soul.life.experience import LifeExperienceStack
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog
from agent.soul.life.orchestrator import ExperienceOrchestrator
from agent.soul.presence.service import PresenceService
from agent.soul.life.experience.ingest.incident import LifeIncident


def test_pipeline_ingest_life_incident_updates_hot_storage(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    pipeline = LifeExperienceStack(life_dir=life_dir)

    result = pipeline.life.ingest_life_incident(
        presence,
        LifeIncident.surprise("tao", hint="路边突然下雨", salience=0.5),
        fallback_narration="路边突然下雨",
        source="surprise",
    )
    assert result.applied
    hot = pipeline.log.recent()
    assert len(hot) == 1
    assert hot[0].source == "surprise"


def test_orchestrator_still_available_via_life_shim(tmp_path):
    log = ExperienceLog(str(tmp_path))
    orch = ExperienceOrchestrator(log=log)
    assert orch._log is log
