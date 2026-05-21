"""Soul 演化与心跳的编排入口。

串联路径
--------
1. 对话后：TaoLoop.post_process → Life.record_turn → 显著体验擢升 Memory
2. 心跳 wander：Memory.persona_clusters → Persona buffer 元数据（仅采集）
3. 心跳 checklist（月度）：Persona.run_monthly_drift（唯一 self_concept 漂移）

职责边界
--------
- Memory：聚类、遗忘、记忆存储与按主题回查
- Persona buffer：主题元数据 + 漂移调度时间
- Persona self_concept：仅 run_monthly_drift 演化（build/rebuild 为初始化/管理）
- Drive.affect：快变情绪（非 self_concept）
"""

from __future__ import annotations

import uuid

from agent.soul.heartbeat.bridge import (
    LifeHeartbeatPort,
    MemoryHeartbeatPort,
    MemoryHeartbeatResult,
    PersonaSnapshot,
)


def new_heartbeat_tick_id() -> str:
    return str(uuid.uuid4())


def run_wander_evolution_step(
    *,
    memory_port: MemoryHeartbeatPort,
    persona_port=None,
    life_port: LifeHeartbeatPort | None = None,
    tick_id: str | None = None,
    drift_intensity_floor: float = 0.05,
) -> MemoryHeartbeatResult:
    """记忆 wander + buffer 采集；Persona self_concept 不在此步漂移。"""
    _ = persona_port
    _ = drift_intensity_floor
    tid = tick_id or new_heartbeat_tick_id()
    snapshot = PersonaSnapshot(tick_id=tid)

    result = memory_port.tick(snapshot)
    result.tick_id = tid
    if result.signal.tick_id == "":
        result.signal.tick_id = tid

    if life_port is not None:
        life_port.receive_experience(result)

    return result
