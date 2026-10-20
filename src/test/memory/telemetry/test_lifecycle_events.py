"""R5.2 事件完备性：life 侧（unit_created / unit_annotated / collapse / session_closed / compression_block）。"""
from __future__ import annotations

from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog
from agent.soul.life.experience.unit_layer.manage.orchestrator import ExperienceUnitManager
from agent.soul.memory.telemetry import events as ev

from .conftest import events_of, read_events


class _FakeMemoryPort:
    def __init__(self):
        self.ingested: list[str] = []

    def ingest_experience(self, unit) -> None:
        self.ingested.append(unit.id)

    def retract_experience(self, experience_id: str) -> bool:
        return True


def _unit(uid="u1", *, promote=False, decided=False, source="dialogue"):
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="sess-1", narration="测试叙事"),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content="说了点什么"),
        feeling=ExperienceFeeling(
            salience=0.6,
            promote_to_memory=promote,
            annotation_decided=decided,
        ),
        source=source,
    )
    unit.id = uid
    return unit


def test_hot_log_append_emits_unit_created(telemetry, tmp_path):
    log = ExperienceLog(str(tmp_path / "life"))
    log.append(_unit())
    [created] = events_of(read_events(telemetry), ev.UNIT_CREATED)
    assert created["source"] == "dialogue"
    assert created["session_id"] == "sess-1"
    assert created["salience"] == 0.6
    assert created["annotation_decided"] is False


def test_promote_decision_outcomes(telemetry, tmp_path):
    manager = ExperienceUnitManager(
        ExperienceLog(str(tmp_path / "life")),
        memory_port=_FakeMemoryPort(),
    )

    # 未标注 → not_promoted
    unannotated = _unit("u-no")
    manager.ingest_authored_unit(unannotated)
    # 标注擢升 → submitted
    promoted = _unit("u-yes", promote=True, decided=True)
    manager.ingest_authored_unit(promoted)

    annotated = events_of(read_events(telemetry), ev.UNIT_ANNOTATED)
    outcomes = {e["unit_id"]: e["outcome"] for e in annotated}
    assert outcomes["u-no"] == "not_promoted"
    assert outcomes["u-yes"] == "submitted"
    decided = {e["unit_id"]: e["promote_to_memory"] for e in annotated}
    assert decided["u-yes"] is True and decided["u-no"] is False


def test_no_port_emits_no_port_outcome(telemetry, tmp_path):
    manager = ExperienceUnitManager(ExperienceLog(str(tmp_path / "life")), memory_port=None)
    manager.ingest_authored_unit(_unit("u1", promote=True, decided=True))
    [annotated] = events_of(read_events(telemetry), ev.UNIT_ANNOTATED)
    assert annotated["outcome"] == "no_port"


def test_collapse_emits_event(telemetry, tmp_path):
    class _FakeCollapser:
        def collapse(self, units):
            return "交会叙事"

    log = ExperienceLog(str(tmp_path / "life"))
    a = _unit("a", source="narrative")
    b = _unit("b", source="surprise")
    log.append(a)
    log.append(b)
    manager = ExperienceUnitManager(log, memory_port=None, collapser=_FakeCollapser())

    incoming = _unit("c", source="user")
    manager.ingest(incoming)  # 应与 narrative/surprise 在窗口内交会折叠

    collapses = events_of(read_events(telemetry), ev.COLLAPSE)
    assert collapses, "交会折叠应发 collapse 事件"
    assert set(collapses[0]["participant_ids"]) == {"a", "b", "c"}
    assert collapses[0]["collision_unit_id"]
