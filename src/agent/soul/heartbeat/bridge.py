"""
heartbeat/bridge.py — 心跳层 Memory / Presence / Persona / Life 接口规范
====================================================================

心跳 wander tick
----------------
1. SoulService 组装 PersonaSnapshot（Presence.affect + self_concept 检索偏置）
2. MemoryService.tick(snapshot) → wander / ruminate / persona_clusters
3. buffer_candidates → Persona buffer 元数据（**不**触发 self_concept 漂移）
4. EmotionalSignal → Presence.affect（快变情绪，**不**是 self_concept 漂移）
5. LifeHeartbeatPort.receive_experience（可选）

唯一 self_concept 漂移
----------------------
Checklist ``PersonaAction.RUN_MONTHLY_DRIFT``：
buffer 主题 → Memory 回查 → Tao 整合 → ``SelfConcept.apply_delta()``
调度参数见 ``SoulConfig.persona_drift_*``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from agent.soul.memory.unit import Valence


# ═══════════════════════════════════════════════════════════════════════════
#  一、跨模块传输数据类型
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PersonaSnapshot:
    """Persona → Memory 方向：心跳时人格层暴露的当前状态快照。

    由 SoulService 组装（Presence.affect + self_concept 检索偏置），
    作为 wander() 的偏置参数传入 MemoryHeartbeatPort.tick()。

    字段
    ----
    emotional_state
        当前命名情绪，如 "焦虑"、"平静"、"好奇"。
        wander() 可将其作为 emotion_hint 传入 by_valence，
        偏置浮现记忆的情绪色彩。

    valence_bias
        当前情感倾向（粗粒度）。
        None 表示中性/不偏置。

    attention_keywords
        当前注意力焦点关键词列表，如 ["项目进度", "自我怀疑"]。
        可用于在 wander 候选池中对 focus 字段做软过滤/加权。

    tick_id
        本次心跳的唯一标识，用于追踪一次 tick 的全链路日志。
    """
    emotional_state: str = ""
    valence_bias: Valence | None = None
    attention_keywords: list[str] = field(default_factory=list)
    persona_profile: str = ""
    tick_id: str = ""


@dataclass
class EmotionalSignal:
    """Memory → Presence 方向：本次心跳记忆浮现的情绪信号（快变，非 self_concept 漂移）。"""
    dominant_emotion: str = ""
    dominant_valence: Valence = Valence.neutral
    intensity: float = 0.0
    source_unit_ids: list[str] = field(default_factory=list)
    narrative_hint: str = ""
    tick_id: str = ""


@dataclass
class MemoryHeartbeatResult:
    """MemoryHeartbeatPort.tick() 的完整返回值。"""

    wandered_ids: list[str] = field(default_factory=list)
    wandered_units: list = field(default_factory=list)   # list[ScoredUnit]
    ruminated_ids: list[str] = field(default_factory=list)
    narrative_triggered: bool = False
    forgotten_count: int = 0
    signal: EmotionalSignal = field(default_factory=EmotionalSignal)
    tick_id: str = ""
    buffer_candidates: list[dict] = field(default_factory=list)
    rumination_buffer_size: int = 0
    rumination_picked_id: str = ""
    rumination_skill: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
#  二、Memory 侧接口（Memory ↔ Heartbeat）
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class MemoryHeartbeatPort(Protocol):
    """Heartbeat 层调用 Memory 层的接口契约。

    MemoryService 需实现此接口（结构子类型，无需显式继承）。

    方法
    ----
    tick(snapshot)
        执行一次完整的心跳记忆处理流程，返回 MemoryHeartbeatResult。

        实现方指引
        ----------
        1. 解析 snapshot.valence_bias / attention_keywords 作为 wander() 偏置
        2. 调用 retriever.wander(n, emotion_weight, noise, ...)
        3. 将 wandered 记忆 id 交给 RuminationService.ruminate()，生成 ReconstructiveMemory
        4. 判断是否触发 NarrativeWriter（如：本次浮现的高情绪记忆 >= 阈值）
        5. 调用 retriever.persona_clusters()，产出 Persona buffer 主题元数据
        6. 从 wandered 记忆中提取情绪信号，构建 EmotionalSignal
        7. 返回完整 MemoryHeartbeatResult

    narrative_threshold
        触发叙事化的情绪强度阈值（浮现记忆中平均 emotion_intensity 超过此值时
        调用 NarrativeWriter）。实现方可以将此值作为构造参数暴露。
    """

    def tick(self, snapshot: PersonaSnapshot) -> MemoryHeartbeatResult:
        """执行一次心跳记忆处理，返回产出报告和情绪信号。"""
        ...


# ═══════════════════════════════════════════════════════════════════════════
#  三、Life 侧接口（Life ↔ Heartbeat，可选）
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class LifeHeartbeatPort(Protocol):
    """Heartbeat 层调用 Life 层的接口契约（可选，非必须实现）。

    LifeManager 可以选择实现此接口，以在心跳时更新 LifeProfile 的叙事积累。

    方法
    ----
    receive_experience(result) → None
        接收一次心跳的完整记忆结果。

        实现方指引
        ----------
        - result.narrative_hint 非空 → 将其追加到 LifeProfile 的 diary/journal
        - result.signal.intensity 高 → 可触发 LifeSynthesis 生成新的人生阶段摘要
        - 此方法不应阻塞，建议内部异步写入
    """

    def receive_experience(self, result: MemoryHeartbeatResult) -> None:
        """接收心跳记忆产出，更新 LifeProfile 的叙事积累。"""
        ...


@runtime_checkable
class MemoryLifecycleHeartbeatPort(Protocol):
    """记忆子系统生命周期（由 checklist FORGET_SCAN / SLEEP 或显式 API 触发）。"""

    def forget_scan(self, threshold: float = 0.05, dry_run: bool = False) -> list[str]:
        ...

    def run_sleep(self, *, tick_id: str = "", dry_run: bool = False) -> Any:
        ...


# ═══════════════════════════════════════════════════════════════════════════
#  四、HeartbeatService 调用骨架（伪代码）
# ═══════════════════════════════════════════════════════════════════════════

# def tick(self) -> None:
#     snapshot = build_persona_snapshot_from_presence_and_self_concept()
#     result = memory_port.tick(snapshot)
#     presence.receive_heartbeat_signal(result.signal)
#     persona.record_cluster_signals(result.buffer_candidates)
#     life_port.receive_experience(result)
#     # self_concept 漂移仅由 checklist RUN_MONTHLY_DRIFT 触发
