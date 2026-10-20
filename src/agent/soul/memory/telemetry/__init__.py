"""记忆成长性观测（PRD：docs/agent/soul/memory/growth-observability-requirements.md）。

- 事件流水：``.react/telemetry/memory_events.jsonl``（append-only，异步落盘）
- 成长快照：``.react/telemetry/snapshots/``（sleep 末尾，以 store 为准）
- 用法：生产代码统一走 ``emit_event``（telemetry 未启用时为纯 no-op）；
  装配侧（facade/build.py）用 ``configure_memory_telemetry`` 显式指定目录。
"""
from __future__ import annotations

import threading

from agent.soul.memory.telemetry.config import MemoryTelemetryConfig
from agent.soul.memory.telemetry.telemetry import MemoryTelemetry

_TelemetryHandle = MemoryTelemetry | None

_TELEMETRY: _TelemetryHandle = None
_TELEMETRY_LOCK = threading.Lock()


def configure_memory_telemetry(cfg: MemoryTelemetryConfig) -> MemoryTelemetry:
    """显式装配（关闭旧实例）；enabled=False 时返回禁用态单例。"""
    global _TELEMETRY
    with _TELEMETRY_LOCK:
        if _TELEMETRY is not None:
            try:
                _TELEMETRY.close()
            except Exception:
                pass
        _TELEMETRY = MemoryTelemetry(cfg)
        return _TELEMETRY


def get_memory_telemetry() -> MemoryTelemetry | None:
    """进程级默认实例（lazy）；默认配置关闭时返回 None（零事件、零对象）。"""
    global _TELEMETRY
    if _TELEMETRY is not None:
        return _TELEMETRY if _TELEMETRY.config.enabled else None
    with _TELEMETRY_LOCK:
        if _TELEMETRY is None:
            cfg = MemoryTelemetryConfig.load_default()
            if not cfg.enabled:
                # 占位禁用单例：后续 emit_event 直接短路，不再反复读配置
                _TELEMETRY = MemoryTelemetry(cfg)
                return None
            _TELEMETRY = MemoryTelemetry(cfg)
        return _TELEMETRY if _TELEMETRY.config.enabled else None


def has_configured_memory_telemetry() -> bool:
    """是否已有显式配置的实例（装配侧据此避免覆盖调用方的定制目录）。"""
    return _TELEMETRY is not None


def reset_memory_telemetry() -> None:
    """关闭并清空单例（测试隔离用）。"""
    global _TELEMETRY
    with _TELEMETRY_LOCK:
        if _TELEMETRY is not None:
            try:
                _TELEMETRY.close()
            except Exception:
                pass
        _TELEMETRY = None


def emit_event(event: str, **fields) -> None:
    """观测统一入口：未启用/装配失败一律静默 no-op（PRD 2.4）。"""
    try:
        telemetry = get_memory_telemetry()
        if telemetry is None:
            return
        telemetry.emit(event, **fields)
    except Exception:
        pass


def shutdown_memory_telemetry() -> None:
    reset_memory_telemetry()


__all__ = [
    "MemoryTelemetry",
    "MemoryTelemetryConfig",
    "configure_memory_telemetry",
    "get_memory_telemetry",
    "has_configured_memory_telemetry",
    "reset_memory_telemetry",
    "shutdown_memory_telemetry",
    "emit_event",
]
