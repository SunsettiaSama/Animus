"""Soul 演化与心跳的编排入口（预留 / 复用）。

串联路径
--------
1. 对话后（非本模块）：TaoLoop.post_process → Memory.ingest_turn + Persona.evolve（状态层缓冲）
2. 心跳 wander（本模块）：Persona.read_state → Memory.tick → Persona.receive_drift（状态漂移）
   + 可选 Persona.apply_associative_seeds（自我认知 · 联想种子）
3. 心跳日更（HeartbeatModule）：Life.run_daily_review + Persona.evolve_self_concept（自我认知 · 日终）
4. Life 虚构叙事：DailySynthesizer / NarrativeArcEvolver（由 HeartbeatModule 触发 LifeManager.run_daily_review）

三重人格演化（与 Heartbeat 的关系）
----------------------------------
- 动态情绪/status：receive_drift / record_interaction / receive_life_context
- 自我认知 self_concept：apply_associative_seeds（wander）+ evolve_self_concept（日终）
- 静态 profile：仍由配置与 Builder 固化；心跳侧不直接改写（预留反思可走独立管线）
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

    供 HeartbeatCoreService 与单元测试复用；调用方负责线程隔离。
    """
    tid = tick_id or new_heartbeat_tick_id()
    snapshot = persona_port.read_state()
    snapshot.tick_id = tid

    result = memory_port.tick(snapshot)
    result.tick_id = tid
    if result.signal.tick_id == "":
        result.signal.tick_id = tid

    if result.signal.intensity > drift_intensity_floor:
        persona_port.receive_drift(result.signal)

    seeds_fn = getattr(persona_port, "apply_associative_seeds", None)
    if callable(seeds_fn) and result.wandered_units:
        seeds_fn(result.wandered_units)

    if life_port is not None:
        life_port.receive_experience(result)

    return result
