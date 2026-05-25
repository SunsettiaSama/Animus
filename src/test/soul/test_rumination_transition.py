from __future__ import annotations

import json

from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult
from agent.soul.presence.service import PresenceService
from agent.soul.presence.fsm.state import PresenceState
from agent.soul.presence.transition.rumination import (
    RuminationFsmRefresher,
    RuminationSignal,
    RuminationTransition,
)


class _RuminationLLM:
    def generate_messages(self, messages, **kwargs) -> str:
        return json.dumps(
            {
                "affect": "那段记忆反刍上来，心里有些发紧。",
                "somatic": "胸口微微一沉。",
                "working_memory": "旧事在心里重新拼合。",
                "thinking": "我在回味它意味着什么。",
                "perception": "当下的一切因这段记忆而略显不同。",
            },
            ensure_ascii=False,
        )


def test_rumination_signal_from_heartbeat_result():
    result = MemoryHeartbeatResult(
        wandered_ids=["w1"],
        ruminated_ids=["r1"],
        signal=EmotionalSignal(
            dominant_emotion="nostalgia",
            intensity=0.6,
            narrative_hint="那天在海边散步",
            tick_id="tick-1",
        ),
        tick_id="tick-1",
    )
    signal = RuminationSignal.from_heartbeat_result(result)
    assert signal is not None
    assert signal.hint == "那天在海边散步"
    assert signal.ruminated_ids == ["r1"]


def test_rumination_signal_skips_empty_payload():
    result = MemoryHeartbeatResult()
    assert RuminationSignal.from_heartbeat_result(result) is None


def test_rumination_transition_refreshes_fsm():
    state = PresenceState()
    transition = RuminationTransition(refresher=RuminationFsmRefresher(_RuminationLLM()))
    result = transition.ingest(
        state,
        RuminationSignal(
            session_id="tao",
            hint="那天在海边散步",
            ruminated_ids=["r1"],
        ),
    )
    assert result.applied is True
    assert result.refresh is not None
    assert "反刍" in state.affect.narrative


def test_presence_ingest_rumination_persists(tmp_path):
    svc = PresenceService(
        life_dir=str(tmp_path),
        rumination_refresher=RuminationFsmRefresher(_RuminationLLM()),
    )
    result = svc.ingest_rumination(
        RuminationSignal(
            session_id="tao",
            hint="旧照片里的笑容",
            ruminated_ids=["r1"],
        ),
    )
    assert result.applied is True
    assert "反刍" in svc.snapshot("tao").state.affect.narrative
