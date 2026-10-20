"""heartbeat 包：六级抽象层级，__init__ 保持轻量（PEP 562 惰性导出）。

层级（依赖只准向下，L(k) 只 import L(<k) 与根叶）::

    probe/       L1 读事实 —— soul 各部位只读采样（绝不抛异常）
    vitals/      L2 折叠变量 —— 探针读数 → SoulVitals 状态快照
    policy/      L3 变量→决策 —— 纯函数（注入/入睡避让、存活判定）
    schedule/    L4 时间→到期 —— checklist 注册表 + task_runner + profiles
    orchestrate/ L5 执行 —— orchestrator / worker / evolution
    runtime/     L6 线程与装配 —— core_service（主循环）/ module（总装）

根叶（横切）：config / window / console_log / tick_log / inject_mailbox。

``bridge`` 是契约叶子，会被 memory 等实现方在 import 期引用；
若这里 eager import ``runtime.module`` 等重模块，会经 handlers
拉回 memory 侧形成环。需要重模块时按原名
``from agent.soul.heartbeat import HeartbeatModule`` 使用即可，
由下方 ``__getattr__`` 现场加载。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅为类型提示；运行时经 __getattr__ 惰性加载
    from agent.soul.heartbeat.config import SoulHeartbeatConfig
    from agent.soul.evolution_capture import EvolutionBeat, EvolutionCapture, EvolutionCaptureReport
    from agent.soul.heartbeat.inject_mailbox import (
        HeartbeatInjectMailbox,
        get_heartbeat_mailbox,
        set_global_mailbox,
    )
    from agent.soul.heartbeat.orchestrate.orchestrator import (
        ChecklistRunResult,
        HeartbeatOrchestrator,
    )
    from agent.soul.heartbeat.orchestrate.worker import SoulEvolutionWorker
    from agent.soul.heartbeat.runtime.core_service import HeartbeatCoreService
    from agent.soul.heartbeat.runtime.module import HeartbeatModule
    from agent.soul.heartbeat.schedule.profiles import (
        _sub_memory_none,
        make_default_scheduler_config,
    )
    from agent.soul.heartbeat.schedule.task_runner import TaskRunner
    from agent.soul.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult
    from agent.soul.heartbeat.vitals.snapshot import SoulVitals, VitalsBuilder

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "SoulHeartbeatConfig": ("agent.soul.heartbeat.config", "SoulHeartbeatConfig"),
    "HeartbeatModule": ("agent.soul.heartbeat.runtime.module", "HeartbeatModule"),
    "HeartbeatCoreService": ("agent.soul.heartbeat.runtime.core_service", "HeartbeatCoreService"),
    "SoulVitals": ("agent.soul.heartbeat.vitals.snapshot", "SoulVitals"),
    "VitalsBuilder": ("agent.soul.heartbeat.vitals.snapshot", "VitalsBuilder"),
    "HeartbeatTickLog": ("agent.soul.heartbeat.tick_log", "HeartbeatTickLog"),
    "HeartbeatTickResult": ("agent.soul.heartbeat.tick_log", "HeartbeatTickResult"),
    "make_default_scheduler_config": ("agent.soul.heartbeat.schedule.profiles", "make_default_scheduler_config"),
    "_sub_memory_none": ("agent.soul.heartbeat.schedule.profiles", "_sub_memory_none"),
    "TaskRunner": ("agent.soul.heartbeat.schedule.task_runner", "TaskRunner"),
    "HeartbeatInjectMailbox": ("agent.soul.heartbeat.inject_mailbox", "HeartbeatInjectMailbox"),
    "get_heartbeat_mailbox": ("agent.soul.heartbeat.inject_mailbox", "get_heartbeat_mailbox"),
    "set_global_mailbox": ("agent.soul.heartbeat.inject_mailbox", "set_global_mailbox"),
    "EvolutionBeat": ("agent.soul.evolution_capture", "EvolutionBeat"),
    "EvolutionCapture": ("agent.soul.evolution_capture", "EvolutionCapture"),
    "EvolutionCaptureReport": ("agent.soul.evolution_capture", "EvolutionCaptureReport"),
    "HeartbeatOrchestrator": ("agent.soul.heartbeat.orchestrate.orchestrator", "HeartbeatOrchestrator"),
    "ChecklistRunResult": ("agent.soul.heartbeat.orchestrate.orchestrator", "ChecklistRunResult"),
    "SoulEvolutionWorker": ("agent.soul.heartbeat.orchestrate.worker", "SoulEvolutionWorker"),
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
