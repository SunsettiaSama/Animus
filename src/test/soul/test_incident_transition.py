from __future__ import annotations

import json

from agent.soul.presence.service import PresenceService
from agent.soul.presence.transition.incident import (
    IncidentFsmRefresher,
    IncidentKind,
    IncidentTransition,
    LifeIncident,
)
from agent.soul.presence.fsm.state import PresenceState


class _IncidentLLM:
    def generate_messages(self, messages, **kwargs) -> str:
        return json.dumps(
            {
                "affect": "这件事让我有些意外。",
                "somatic": "胸口微微一紧。",
                "working_memory": "记住了这次地标兑现。",
                "thinking": "我在回味它意味着什么。",
                "perception": "生活像被轻轻推了一下。",
            },
            ensure_ascii=False,
        )


def test_incident_transition_refreshes_fsm():
    state = PresenceState()
    transition = IncidentTransition(refresher=IncidentFsmRefresher(_IncidentLLM()))
    result = transition.ingest(
        state,
        LifeIncident.surprise("tao", hint="路边突然下雨"),
    )
    assert result.applied is True
    assert result.refresh is not None
    assert "意外" in state.affect.narrative


def test_presence_ingest_incident_persists(tmp_path):
    svc = PresenceService(
        life_dir=str(tmp_path),
        incident_refresher=IncidentFsmRefresher(_IncidentLLM()),
    )
    result = svc.ingest_incident(
        LifeIncident.landmark_filled("tao", hint="终于去了海边"),
    )
    assert result.applied is True
    assert "意外" in svc.snapshot("tao").state.affect.narrative


def test_landmark_planned_and_filled_use_distinct_kinds():
    planned = LifeIncident.landmark_planned("tao", hint="计划去海边")
    filled = LifeIncident.landmark_filled("tao", hint="去了海边")
    assert planned.kind == IncidentKind.landmark_planned
    assert filled.kind == IncidentKind.landmark_filled
