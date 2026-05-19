"""Soul 演化与心跳的编排入口。

串联路径
--------
1. 对话后（非本模块）：TaoLoop.post_process → Memory.ingest_turn + Persona.evolve（状态层缓冲）
2. 心跳 tick（轻量）：HeartbeatModule → Orchestrator.run_due → 重项入 SoulEvolutionWorker
3. 心跳演化（worker）：run_wander_evolution_step / flush / landmark / 日终 Tao 等

三重人格演化（与 Heartbeat 的关系）
----------------------------------
- 动态情绪/status：receive_drift / record_interaction / receive_life_context（对话 + wander 路径）
- 自我认知 self_concept：apply_associative_seeds（wander）+ run_daily_reflection（Base Tao 日终）
- 静态 profile：仍由配置与 Builder 固化；心跳侧不直接改写
"""

from __future__ import annotations

import uuid

from agent.soul.heartbeat.bridge import (
    LifeHeartbeatPort,
    MemoryHeartbeatPort,
    MemoryHeartbeatResult,
    PersonaHeartbeatPort,
)


def new_heartbeat_tick_id() -> str:
    return str(uuid.uuid4())


def run_wander_evolution_step(
    *,
    memory_port: MemoryHeartbeatPort,
    persona_port: PersonaHeartbeatPort,
    life_port: LifeHeartbeatPort | None = None,
    tick_id: str | None = None,
    drift_intensity_floor: float = 0.05,
) -> MemoryHeartbeatResult:
    """执行一轮「记忆漂移 → 人格漂移 → 可选 life 入账」。

    由 SoulEvolutionWorker 异步调用；heartbeat tick 只负责入队。
    """
    tid = tick_id or new_heartbeat_tick_id()
    snapshot = persona_port.read_state()
    snapshot.tick_id = tid

    result = memory_port.tick(snapshot)
    result.tick_id = tid
    if result.signal.tick_id == "":
        result.signal.tick_id = tid

    apply_fn = getattr(persona_port, "apply_wander_result", None)
    if callable(apply_fn):
        apply_fn(result, drift_intensity_floor)
    else:
        if result.signal.intensity > drift_intensity_floor:
            persona_port.receive_drift(result.signal)
        seeds_fn = getattr(persona_port, "apply_associative_seeds", None)
        if callable(seeds_fn) and result.wandered_units:
            seeds_fn(result.wandered_units)

    if life_port is not None:
        life_port.receive_experience(result)

    return result
