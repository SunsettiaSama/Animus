from __future__ import annotations

import json

from agent.soul.presence.fsm.events import PresenceEvent
from agent.soul.presence.service import PresenceService
from agent.soul.presence.transition import (
    IncidentFsmRefresher,
    LifeIncident,
    PresenceTrigger,
    PresenceTriggerKind,
    PresenceTransitionEngine,
)


class _IncidentLLM:
    def generate_messages(self, messages, **kwargs) -> str:
        return json.dumps(
            {
                "affect": "统一 trigger 刷新成功。",
                "somatic": "身体微微一紧。",
                "working_memory": "记住了这次事件。",
                "thinking": "我在回味它意味着什么。",
                "perception": "生活像被轻轻推了一下。",
            },
            ensure_ascii=False,
        )


def test_presence_trigger_routes_incident(tmp_path):
    engine = PresenceTransitionEngine.from_refreshers(
        incident_refresher=IncidentFsmRefresher(_IncidentLLM()),
    )
    svc = PresenceService(life_dir=str(tmp_path), transition_engine=engine)
    incident = LifeIncident.surprise("tao", hint="路边突然下雨")
    trigger = PresenceTrigger.incident(incident)

    assert trigger.kind == PresenceTriggerKind.incident
    assert trigger.label == "surprise"

    result = svc.interface.trigger(trigger)
    assert result.applied is True
    assert result.outcome.incident is not None
    assert "统一 trigger" in svc.snapshot("tao").state.affect.narrative


def test_presence_trigger_boundary_delegates_to_ingest():
    svc = PresenceService()
    event = PresenceEvent.user_text("tao")
    trigger = PresenceTrigger.boundary(event)

    trigger_result = svc.interface.trigger(trigger)
    ingest_result = svc.interface.boundary(event)

    assert trigger_result.boundary is True
    assert trigger_result.after == ingest_result.after
    assert trigger_result.outcome.boundary is not None
