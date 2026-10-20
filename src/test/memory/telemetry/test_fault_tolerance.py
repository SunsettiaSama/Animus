"""R5.3 故障容忍：telemetry 落盘不可用时，检索与记忆写入不受影响。"""
from __future__ import annotations

import pytest

from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.telemetry import (
    MemoryTelemetryConfig,
    configure_memory_telemetry,
    emit_event,
    reset_memory_telemetry,
)
from agent.soul.memory.telemetry.store_hooks import TelemetryNodeStore


@pytest.fixture()
def broken_telemetry(tmp_path):
    """dir 指向一个已存在的文件 → mkdir/open 全失败。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    configure_memory_telemetry(
        MemoryTelemetryConfig(enabled=True, dir=str(blocker / "telemetry"))
    )
    yield
    reset_memory_telemetry()


def test_emit_never_raises_when_unwritable(broken_telemetry):
    emit_event("unit_created", unit_id="x")  # 不应抛异常
    emit_event("recall_recorded", node_id="y")


def test_hot_log_still_writes_when_telemetry_broken(broken_telemetry, tmp_path):
    log = ExperienceLog(str(tmp_path / "life"))
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="s", narration="n"),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content="c"),
        feeling=ExperienceFeeling(salience=0.5),
        source="dialogue",
    )
    log.append(unit)
    assert log.get_by_id(unit.id) is not None, "记忆写入不受观测故障影响"


def test_node_store_still_writes_when_telemetry_broken(broken_telemetry):
    class _Inner:
        def __init__(self):
            self.rows = {}

        def put(self, node):
            self.rows[node.id] = node

        def get(self, node_id):
            return self.rows.get(node_id)

    inner = _Inner()
    wrapped = TelemetryNodeStore(inner)
    node = FactualMemory(id="n1", focus="f", fact="x")
    wrapped.put(node)  # 不应抛异常
    assert inner.rows["n1"] is node


def test_search_instrumentation_never_raises(broken_telemetry):
    """入口 A 的埋点辅助在故障态也应静默。"""
    from agent.soul.memory.facade.service import MemoryService

    MemoryService._emit_search_telemetry("hybrid", {"query": "q"}, [{"id": "1", "final_score": 0.5}], 0.0)
