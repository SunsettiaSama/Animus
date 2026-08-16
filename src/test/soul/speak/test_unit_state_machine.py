from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
    RhythmScheduleDirector,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
    CharacterRhythmSchedule,
    ExecutableUnit,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
    InteractionUnit,
    PlotArc,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.types import (
    DialogueSnapshot,
    SessionRuntimeSnapshot,
    SessionSignals,
    SessionSnapshot,
    build_snapshot_id,
)


class _PayloadLLM:
    available = True

    def __init__(self, payload: dict) -> None:
        import json

        self._raw = json.dumps(payload)

    def generate_json(self, **kwargs):
        del kwargs
        return self._raw


def _snapshot() -> SessionSnapshot:
    return SessionSnapshot(
        schema_version=1,
        snapshot_id=build_snapshot_id("s1", turn_index=1, generation=0),
        session_id="s1",
        signals=SessionSignals(session_id="s1", turn_index=1, generation=0),
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(working_memory=""),
    )


def test_reject_update_on_completed_plot_unit():
    now = time.time()
    plot = PlotArc(
        summary="弧",
        units=[
            InteractionUnit(
                unit_id="plot-done",
                intent="已完成的动作",
                status="done",
            ),
            InteractionUnit(
                unit_id="plot-active",
                intent="当前动作",
                status="active",
            ),
        ],
    )
    current = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-1",
                open_at=now - 1,
                plot_unit_ids=("plot-done",),
                script_text="旧台本",
                detail="你按旧的做",
                status="pending",
            )
        ]
    )
    director = RhythmScheduleDirector(
        _PayloadLLM(
            {
                "action": "update",
                "executable_units": [
                    {
                        "unit_id": "exec-1",
                        "plot_unit_id": "plot-done",
                        "script_text": "试图更新已完成 unit",
                        "detail": "你不该改到已完成卡",
                    }
                ],
            }
        )
    )
    out = director.run(
        _snapshot(),
        current=current,
        user_text="",
        dialogue_history="",
        force_open_now=False,
        poll=True,
        plot_arc=plot,
        revise=True,
    )
    schedule = CharacterRhythmSchedule.from_dict(out.payload["schedule"])
    entry = next(e for e in schedule.executable_units if e.unit_id == "exec-1")
    assert entry.script_text == "旧台本"


def test_poll_without_refill_keeps_schedule_and_has_no_complete_flag():
    now = time.time()
    current = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id=f"exec-{i}",
                plot_unit_id=f"p{i}",
                open_at=now + 10,
                status="pending",
                detail="你继续",
            )
            for i in range(5)
        ]
    )
    director = RhythmScheduleDirector(
        _PayloadLLM(
            {
                "action": "refill",
                "executable_units": [
                    {
                        "plot_unit_id": "extra",
                        "detail": "不该跑到这里",
                        "reason": "noise",
                    }
                ],
            }
        )
    )
    out = director.run(
        _snapshot(),
        current=current,
        user_text="",
        dialogue_history="",
        force_open_now=False,
        poll=True,
    )
    assert out.payload["action"] == "keep"
    assert "interaction_unit_complete" not in out.payload
    schedule = CharacterRhythmSchedule.from_dict(out.payload["schedule"])
    assert len([e for e in schedule.executable_units if e.status == "pending"]) == 5
