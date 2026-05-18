"""
heartbeat/bridge.py — 心跳层的双向接口规范
==========================================

心跳层是 Memory 和 Persona 之间的**唯一桥梁**，
负责在"漫无目的的思考"期间驱动记忆沉淀与人格漂移。

                    ┌─────────────────────────────────┐
                    │         HeartbeatService         │
                    │   （调度触发，每 N 小时一次）      │
                    └──────────────┬──────────────────┘
                    MemoryHBPort   │   PersonaHBPort
              ┌────────────────────┼────────────────────┐
              ▼                    │                    ▼
     ┌────────────────┐            │          ┌────────────────┐
     │  MemoryService │            │          │ PersonaManager │
     │  (soul/memory) │            │          │ (soul/persona) │
     └────────────────┘            │          └────────────────┘
              │                    │                    │
              │  MemoryHeartbeatResult                  │
              │ ────────────────────────────────────▶   │
              │                    │                    │
              │            EmotionalSignal              │
              │ ◀────────────────────────────────────   │
              │          (已由 PersonaHBPort 返回)       │
              │                    │                    │

调用序列（HeartbeatService.tick()）
------------------------------------
1. persona_port.read_state()          → PersonaSnapshot
                                        （读取当前情绪状态和注意力偏置，供记忆层偏置检索）

2. memory_port.tick(PersonaSnapshot)  → MemoryHeartbeatResult
   内部步骤：
     2a. retriever.wander(...)         # 漂移式采样，基于情绪偏置
     2b. MemoryService.ruminate(...)    # STM/LTM 统一反刍，生成 ReconstructiveMemory（可链式）
     2c. (可选) NarrativeWriter        # 高情绪密度时自动触发叙事化
     2d. (可选) FlushEngine.run()      # 若距上次 flush 超过阈值，执行 STM→LTM 归档

3. persona_port.receive_drift(signal) # 将记忆层产出的情绪信号注入人格演化
   内部步骤：
     3a. EmotionalStateEvolver.update(...)   # 更新情绪 texture + anchors
     3b. (可选) PersonaEvolver.reflect(...)  # 若信号强度高，触发深层人格反思

4. (可选) life_port.receive_experience(result)
   内部步骤：
     4a. LifeManager 将本次心跳的叙事 hint 写入 LifeProfile

双向接口原则
------------
- Memory ← Persona：PersonaSnapshot 作为"注意力偏置"输入 wander()
  具体体现：valence_bias / attention_keywords 偏移 wander 的情绪权重

- Memory → Persona：EmotionalSignal 作为"情绪输入"触发人格漂移
  具体体现：dominant_emotion / intensity → EmotionalAnchor 写入 EmotionalState

- 心跳层不持有任何业务状态，仅协调两端的数据流动
- 接口均为 Protocol（结构子类型），实现方无需继承
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from agent.soul.memory.unit import Valence


# ═══════════════════════════════════════════════════════════════════════════
#  一、跨模块传输数据类型
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PersonaSnapshot:
    """Persona → Memory 方向：心跳时人格层暴露的当前状态快照。

    由 PersonaHeartbeatPort.read_state() 返回，
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
    tick_id: str = ""


@dataclass
class EmotionalSignal:
    """Memory → Persona 方向：本次心跳中记忆浮现所产生的情绪信号。

    由 MemoryHeartbeatPort.tick() 返回，
    传入 PersonaHeartbeatPort.receive_drift() 驱动人格演化。

    字段
    ----
    dominant_emotion
        本次浮现记忆中主导的命名情绪，取 intensity 最高的记忆的 emotion。
        若所有记忆情绪烈度为 0，则为空字符串（无情绪信号，persona 层可忽略）。

    dominant_valence
        主导情感倾向。

    intensity
        综合情绪强度，取所有浮现记忆 emotion_intensity 的加权平均。
        范围 [0, 1]。

    source_unit_ids
        产生此信号的记忆 ID 列表，用于追溯与审计。

    narrative_hint
        可选的叙事线索文本，从 ReconstructiveMemory 的 reconstructed_fact 中提取。
        LifeManager 可将其写入 LifeProfile 的日记式摘要。

    tick_id
        与 PersonaSnapshot.tick_id 对应，保持一次心跳的链路完整性。
    """
    dominant_emotion: str = ""
    dominant_valence: Valence = Valence.neutral
    intensity: float = 0.0
    source_unit_ids: list[str] = field(default_factory=list)
    narrative_hint: str = ""
    tick_id: str = ""


@dataclass
class MemoryHeartbeatResult:
    """MemoryHeartbeatPort.tick() 的完整返回值。

    包含本次心跳记忆处理的全部产出，供：
    - HeartbeatService 决定是否触发叙事写入
    - PersonaHeartbeatPort 接收情绪信号
    - LifeHeartbeatPort 接收经验摘要

    字段
    ----
    wandered_ids
        本次 wander() 采样到的记忆 ID 列表（可能为空，如果 STM/LTM 均无内容）。

    wandered_units
        本次 wander() 浮现的完整 ScoredUnit 列表（list[ScoredUnit]，松散类型避免循环依赖）。
        供 AssociativeEvolver 做跨记忆模式分析使用。

    ruminated_ids
        本轮记忆层 ruminate 成功产生的 ReconstructiveMemory ID 列表。

    narrative_triggered
        本次是否触发了 NarrativeWriter（叙事化阈值被满足）。

    flushed_count
        本次 FlushEngine.run() 写入 LTM 的记忆条数（0 表示未触发 flush）。

    signal
        向人格层发送的情绪信号。若本次无记忆浮现，signal.intensity == 0。

    tick_id
        链路 ID，与 PersonaSnapshot.tick_id 一致。
    """
    wandered_ids: list[str] = field(default_factory=list)
    wandered_units: list = field(default_factory=list)   # list[ScoredUnit]
    ruminated_ids: list[str] = field(default_factory=list)
    narrative_triggered: bool = False
    flushed_count: int = 0
    signal: EmotionalSignal = field(default_factory=EmotionalSignal)
    tick_id: str = ""


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
        3. 将 wandered 记忆 id 交给 MemoryService.ruminate()，生成 ReconstructiveMemory
        4. 判断是否触发 NarrativeWriter（如：本次浮现的高情绪记忆 >= N 条）
        5. 判断是否触发 FlushEngine.run()（如：距上次 flush 超过阈值时间）
        6. 从 wandered 记忆中提取情绪信号，构建 EmotionalSignal
        7. 返回完整 MemoryHeartbeatResult

    narrative_threshold
        触发叙事化的情绪强度阈值（浮现记忆中平均 emotion_intensity 超过此值时
        调用 NarrativeWriter）。实现方可以将此值作为构造参数暴露。

    flush_interval_hours
        两次 FlushEngine 调用的最小间隔（小时）。
        实现方应在内部维护 last_flush_time 并比较。
    """

    def tick(self, snapshot: PersonaSnapshot) -> MemoryHeartbeatResult:
        """执行一次心跳记忆处理，返回产出报告和情绪信号。"""
        ...


# ═══════════════════════════════════════════════════════════════════════════
#  三、Persona 侧接口（Persona ↔ Heartbeat）
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class PersonaHeartbeatPort(Protocol):
    """Heartbeat 层调用 Persona 层的接口契约。

    PersonaManager 需实现此接口（结构子类型，无需显式继承）。

    方法
    ----
    read_state() → PersonaSnapshot
        读取当前人格状态快照。
        应是轻量操作（从内存中读取已加载的 EmotionalState + PreferenceStore），
        不应触发 I/O 或 LLM 调用。

    receive_drift(signal) → None
        接收来自记忆层的情绪信号，驱动人格演化。

        实现方指引
        ----------
        - signal.intensity == 0.0 → 无情绪信号，可直接返回
        - signal.intensity < 阈值（如 0.3）→ 仅写入 EmotionalAnchor，不触发 LLM 反思
        - signal.intensity >= 阈值 → 写入 anchor + 触发 EmotionalStateEvolver 更新 texture
        - signal.intensity >= 高阈值（如 0.7）→ 可选触发 PersonaEvolver.reflect()
          进行深层人格反思（更新 profile.values / profile.traits）

        注意：receive_drift() 本身应是同步的；若 LLM 调用耗时，实现方应内部
        另起后台线程，不阻塞 HeartbeatService.tick() 的主流程。
    """

    def read_state(self) -> PersonaSnapshot:
        """返回当前人格状态快照（轻量，无 I/O）。"""
        ...

    def receive_drift(self, signal: EmotionalSignal) -> None:
        """接收情绪信号，驱动 EmotionalState 演化。"""
        ...


@runtime_checkable
class PersonaAssociativeHeartbeatPort(Protocol):
    """人格心跳扩展：联想种子（wander → SelfConcept emerging）。

    PersonaManager 实现此法；纯 Status-only 桩可不实现。
    """

    def apply_associative_seeds(self, wandered_units: list) -> bool:
        ...


@runtime_checkable
class PersonaSelfConceptHeartbeatPort(Protocol):
    """人格心跳扩展：自我叙事 / 信念日终演化。

    由 HeartbeatModule 日终路径调用，而非 wander 线程。
    """

    def evolve_self_concept(
        self,
        recent_anchors: list | None = None,
        recent_ruminations: list | None = None,
    ) -> bool:
        ...


@runtime_checkable
class MemoryLifecycleHeartbeatPort(Protocol):
    """记忆子系统生命周期（预留：由调度器或显式任务触发，不必绑在每次 wander）。"""

    def flush(self) -> object:
        ...

    def forget_scan(self, threshold: float = 0.05, dry_run: bool = False) -> list[str]:
        ...


# ═══════════════════════════════════════════════════════════════════════════
#  四、Life 侧接口（Life ↔ Heartbeat，可选）
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


# ═══════════════════════════════════════════════════════════════════════════
#  五、HeartbeatService 的调用骨架（伪代码，供实现参考）
# ═══════════════════════════════════════════════════════════════════════════

# class HeartbeatService:
#     """
#     def __init__(
#         self,
#         memory_port: MemoryHeartbeatPort,
#         persona_port: PersonaHeartbeatPort,
#         life_port: LifeHeartbeatPort | None = None,
#         tick_interval_hours: float = 6.0,
#     ): ...
#
#     def tick(self) -> None:
#         tick_id = _new_tick_id()
#
#         # 1. 读取人格快照（偏置参数来源）
#         snapshot = self.persona_port.read_state()
#         snapshot.tick_id = tick_id
#
#         # 2. 驱动记忆处理（wander → ruminate → 可选 narrative → 可选 flush）
#         result = self.memory_port.tick(snapshot)
#         result.tick_id = tick_id
#
#         # 3. 人格漂移（情绪信号注入）
#         self.persona_port.receive_drift(result.signal)
#
#         # 4. 生命叙事更新（可选）
#         if self.life_port is not None:
#             self.life_port.receive_experience(result)
#     """
