"""telemetry 测试共用工装：隔离的 telemetry 实例 + 事件收集。"""
from __future__ import annotations

import json

import pytest

from agent.soul.memory.telemetry import (
    MemoryTelemetryConfig,
    configure_memory_telemetry,
    reset_memory_telemetry,
)


@pytest.fixture()
def telemetry(tmp_path):
    """启用态 telemetry，指向 tmp；用例结束关闭并复位单例。"""
    cfg = MemoryTelemetryConfig(enabled=True, dir=str(tmp_path / "telemetry"))
    instance = configure_memory_telemetry(cfg)
    yield instance
    reset_memory_telemetry()


@pytest.fixture()
def telemetry_off():
    """禁用态（零对象）：get_memory_telemetry 应返回 None。"""
    configure_memory_telemetry(MemoryTelemetryConfig(enabled=False, dir="unused"))
    yield
    reset_memory_telemetry()


def read_events(instance) -> list[dict]:
    instance.flush(timeout=5.0)
    events = list(instance.iter_events())
    return events


def events_of(events: list[dict], name: str) -> list[dict]:
    return [e for e in events if e.get("event") == name]


def write_events_file(path, events) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return str(path)
