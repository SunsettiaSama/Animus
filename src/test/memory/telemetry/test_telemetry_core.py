"""R1 机制测试：异步队列、落盘、轮转、丢弃计数、配置解析。"""
from __future__ import annotations

import json

from agent.soul.memory.telemetry import (
    MemoryTelemetryConfig,
    get_memory_telemetry,
    reset_memory_telemetry,
)
from agent.soul.memory.telemetry.config import _default_yaml_path


def test_emit_writes_jsonl_async(telemetry):
    telemetry.emit("unit_created", unit_id="u1", source="dialogue")
    telemetry.flush(timeout=5.0)
    events = list(telemetry.iter_events())
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "unit_created"
    assert e["unit_id"] == "u1"
    assert e["ts"]


def test_queue_overflow_drops_oldest_and_counts(tmp_path):
    cfg = MemoryTelemetryConfig(enabled=True, dir=str(tmp_path / "t"), queue_size=4)
    from agent.soul.memory.telemetry import configure_memory_telemetry

    t = configure_memory_telemetry(cfg)
    try:
        for i in range(10):
            t.emit("recall_recorded", node_id=f"n{i}")
        t.flush(timeout=5.0)
        stats = t.stats()
        assert stats["dropped"] >= 6
        assert stats["emitted"] == 10
        kept = [e for e in t.iter_events() if e["event"] == "recall_recorded"]
        # 丢最旧保最新
        assert {e["node_id"] for e in kept} == {f"n{i}" for i in range(6, 10)}
    finally:
        reset_memory_telemetry()


def test_rotation_single_generation(tmp_path):
    cfg = MemoryTelemetryConfig(
        enabled=True, dir=str(tmp_path / "t"), max_events_bytes=1
    )
    from agent.soul.memory.telemetry import configure_memory_telemetry

    t = configure_memory_telemetry(cfg)
    try:
        t.emit("unit_created", unit_id="a")
        t.flush(timeout=5.0)  # 确保 a 先落盘，形成既有文件
        t.emit("unit_created", unit_id="b")
        t.flush(timeout=5.0)
        rotated = tmp_path / "t" / "memory_events.jsonl.1"
        assert rotated.exists(), "超限后应单代轮转出 .1"
        all_events = list(t.iter_events())
        assert {e.get("unit_id") for e in all_events} == {"a", "b"}
    finally:
        reset_memory_telemetry()


def test_disabled_config_returns_none_singleton(telemetry_off):
    from agent.soul.memory.telemetry import emit_event

    assert get_memory_telemetry() is None
    # 关闭态 emit 是纯 no-op，不构造文件
    emit_event("unit_created", unit_id="x")


def test_default_yaml_has_telemetry_group():
    assert _default_yaml_path().is_file()
    import yaml

    data = yaml.safe_load(_default_yaml_path().read_text(encoding="utf-8"))
    assert isinstance(data.get("telemetry"), dict), "service.yaml 应含 telemetry 组"


def test_snapshot_write_and_marker_event(telemetry, tmp_path):
    telemetry.write_snapshot({"ts": "2026-09-25T00:00:00", "node_count": 3, "edge_count": 2})
    files = list(telemetry.config.snapshot_dir.glob("*_growth_snapshot.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["node_count"] == 3
    events = list(telemetry.iter_events())
    assert any(e.get("event") == "snapshot_taken" and e.get("node_count") == 3 for e in events)
