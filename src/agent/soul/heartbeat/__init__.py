"""heartbeat 包：__init__ 保持轻量（PEP 562 惰性导出）。

``bridge`` 是契约叶子，会被 memory 等实现方在 import 期引用；
若这里 eager import ``module`` / ``core_service`` 等重模块，
会经 handlers 拉回 memory 侧形成环。需要重模块时按原名
``from agent.soul.heartbeat import HeartbeatModule`` 使用即可，
由下方 ``__getattr__`` 现场加载。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅为类型提示；运行时经 __getattr__ 惰性加载
    from agent.soul.heartbeat.config import SoulHeartbeatConfig
    from agent.soul.heartbeat.core_service import HeartbeatCoreService
    from agent.soul.heartbeat.evolution import new_heartbeat_tick_id, run_wander_evolution_step
    from agent.soul.heartbeat.evolution_capture import (
        EvolutionBeat,
        EvolutionCapture,
        EvolutionCaptureReport,
    )
    from agent.soul.heartbeat.inject_mailbox import (
        HeartbeatInjectMailbox,
        get_heartbeat_mailbox,
        set_global_mailbox,
    )
    from agent.soul.heartbeat.module import HeartbeatModule
    from agent.soul.heartbeat.orchestrator import ChecklistRunResult, HeartbeatOrchestrator
    from agent.soul.heartbeat.profiles import _sub_memory_none, make_default_scheduler_config
    from agent.soul.heartbeat.task_runner import TaskRunner
    from agent.soul.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult
    from agent.soul.heartbeat.worker import SoulEvolutionWorker

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "SoulHeartbeatConfig": ("agent.soul.heartbeat.config", "SoulHeartbeatConfig"),
    "HeartbeatModule": ("agent.soul.heartbeat.module", "HeartbeatModule"),
    "HeartbeatTickLog": ("agent.soul.heartbeat.tick_log", "HeartbeatTickLog"),
    "HeartbeatTickResult": ("agent.soul.heartbeat.tick_log", "HeartbeatTickResult"),
    "make_default_scheduler_config": ("agent.soul.heartbeat.profiles", "make_default_scheduler_config"),
    "_sub_memory_none": ("agent.soul.heartbeat.profiles", "_sub_memory_none"),
    "TaskRunner": ("agent.soul.heartbeat.task_runner", "TaskRunner"),
    "HeartbeatInjectMailbox": ("agent.soul.heartbeat.inject_mailbox", "HeartbeatInjectMailbox"),
    "get_heartbeat_mailbox": ("agent.soul.heartbeat.inject_mailbox", "get_heartbeat_mailbox"),
    "set_global_mailbox": ("agent.soul.heartbeat.inject_mailbox", "set_global_mailbox"),
    "HeartbeatCoreService": ("agent.soul.heartbeat.core_service", "HeartbeatCoreService"),
    "new_heartbeat_tick_id": ("agent.soul.heartbeat.evolution", "new_heartbeat_tick_id"),
    "run_wander_evolution_step": ("agent.soul.heartbeat.evolution", "run_wander_evolution_step"),
    "EvolutionBeat": ("agent.soul.heartbeat.evolution_capture", "EvolutionBeat"),
    "EvolutionCapture": ("agent.soul.heartbeat.evolution_capture", "EvolutionCapture"),
    "EvolutionCaptureReport": ("agent.soul.heartbeat.evolution_capture", "EvolutionCaptureReport"),
    "HeartbeatOrchestrator": ("agent.soul.heartbeat.orchestrator", "HeartbeatOrchestrator"),
    "ChecklistRunResult": ("agent.soul.heartbeat.orchestrator", "ChecklistRunResult"),
    "SoulEvolutionWorker": ("agent.soul.heartbeat.worker", "SoulEvolutionWorker"),
}

__all__ = list(_LAZY_IMPORTS)


def __getattr__(name: str):
    entry = _LAZY_IMPORTS.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr = entry
    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value  # 命中后缓存，后续直接命中
    return value
