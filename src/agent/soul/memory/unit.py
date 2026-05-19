from __future__ import annotations

import math
import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar


# ── Enumerations ──────────────────────────────────────────────────────────────

class Valence(str, Enum):
    """情感倾向枚举——粗粒度路由标签，仅供检索偏置使用。

    不表达体验的精确度；精确描述由 `emotion`（命名情绪）和
    `emotion_intensity`（烈度）承载。
    """
    positive = "positive"
    negative = "negative"
    mixed    = "mixed"
    neutral  = "neutral"


class MemoryTier(str, Enum):
    short_term = "short_term"  # 短期记忆（Redis，快速衰减）
    long       = "long"        # 长期记忆（MySQL + Qdrant，慢衰减）


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


# ── Abstract Base ─────────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class MemoryUnit(ABC):
    """所有记忆单元的抽象基类。

    情绪的三个表达层次
    ------------------
    - `perception`（文本，子类独有）：完整的主观体验叙述，给 LLM 读，
      允许模糊、复杂、矛盾，不做任何量化。
    - `emotion`（命名字符串）：指向具体情绪的方向，如"伤心"、"好奇"、
      "焦虑"、"矛盾"、"释然"；自由字符串，不约束词汇表。
    - `emotion_intensity`（float 0~1）：情绪烈度，供激活度公式使用；
      例：emotion="伤心", emotion_intensity=0.3。
    - `valence`（枚举）：由以上两项派生的粗粒度路由标签，供检索过滤。

    激活度公式
    ----------
    A(t) = base × e^(-ln2/T½ · Δt) + log(1 + recall) + intensity × 0.5
    """

    MEMORY_TYPE: ClassVar[str]  # 子类必须定义

    # ── 语义锚点 ─────────────────────────────────────────────────────────────
    focus: str

    # ── 情绪结构化字段 ────────────────────────────────────────────────────────
    emotion:           str     = ""              # 命名情绪（方向）
    emotion_intensity: float   = 0.0             # 烈度 0~1.0
    valence:           Valence = Valence.neutral  # 粗粒度路由（可由外部推断设定）

    # ── 激活度元数据 ──────────────────────────────────────────────────────────
    tier:                MemoryTier = MemoryTier.short_term
    base_activation:     float      = 0.5
    recall_count:        int        = 0   # 被 recall() 命中的次数
    rehearsal_count:     int        = 0   # 心跳反刍次数
    narrative_ref_count: int        = 0   # 被 NarrativeMemory 引用的次数
    last_accessed:       datetime   = field(default_factory=_now)
    created_at:          datetime   = field(default_factory=_now)
    meta:                dict       = field(default_factory=dict)
    id:                  str        = field(default_factory=_uid)

    # ── 激活度（懒计算，不持久化）────────────────────────────────────────────

    def activation(
        self,
        now: datetime | None = None,
        half_life_days: float = 7.0,
    ) -> float:
        """实时激活度，结果裁剪到 [0, 1]。

        工作记忆建议 half_life_days=3，长期记忆建议 30。
        """
        if now is None:
            now = _now()
        delta = (now - self.last_accessed).total_seconds() / 86400.0
        decay = math.exp(-math.log(2) / half_life_days * max(delta, 0.0))
        boost_recall  = math.log1p(self.recall_count)
        boost_emotion = self.emotion_intensity * 0.5
        return min(1.0, self.base_activation * decay + boost_recall + boost_emotion)

    # ── 状态变更辅助 ──────────────────────────────────────────────────────────

    def on_recall(self) -> None:
        """被检索命中后调用：更新访问时间与回忆计数。"""
        self.recall_count += 1
        self.last_accessed = _now()

    def on_rehearsal(self) -> None:
        """被反刍使用后调用：递增 rehearsal_count 并刷新访问时间。"""
        self.rehearsal_count += 1
        self.last_accessed = _now()

    def promote_to_long(self) -> None:
        """晋升至长期记忆（由遗忘引擎或 Processor 调用）。"""
        self.tier = MemoryTier.long

    @classmethod
    def type_name(cls) -> str:
        return cls.MEMORY_TYPE


# ── Factual Memory ────────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class FactualMemory(MemoryUnit):
    """事实性记忆：记录发生了什么，以及 Agent 当时的主观感知。

    `fact` 是客观陈述，不应被修改。
    `perception` 是 Agent 自己的感知叙述——文本而非数值，
    允许模糊、复杂和矛盾（"感到一种说不清的满足，同时有些不安"）。

    示例
    ----
        FactualMemory(
            focus    = "架构讨论：soul 层拆分",
            fact     = "用户要求将长期记忆迁移到 soul 层，删除 react 侧短期记忆模块",
            perception = "思路逐渐清晰，但对工程量有些担忧，不确定边界是否画得足够干净",
            emotion           = "焦虑",
            emotion_intensity = 0.4,
            valence           = Valence.mixed,
            base_activation   = 0.7,
        )
    """

    MEMORY_TYPE = "factual"

    fact:           str       # 客观事实（从 ExperienceUnit / Chronicle 派生或直接复制）
    perception:     str       # Agent 主观感知（自然语言叙述，无量化约束）
    life_event_id:  str = ""  # 关联的 ExperienceUnit.id（可为空表示遗留数据）


# ── Reconstructive Memory ─────────────────────────────────────────────────────

@dataclass(kw_only=True)
class ReconstructiveMemory(MemoryUnit):
    """重构型记忆：反刍时对上一跳材料的重新解读，允许扭曲与篡改。

    对应「记忆再巩固」：``source_id`` 指向**直接父节点**——可以是
    :class:`FactualMemory`，也可以是另一条 :class:`ReconstructiveMemory`，
    从而形成同一叙事链条上的多次迭代偏差。
    ``meta`` 中可含 ``rumination_root_id``（锚定最初事实记忆 id）。

    `trigger` 记录本次重构的外显情境（如心跳时的情绪快照）。
    """

    MEMORY_TYPE = "reconstructive"

    source_id:          str  # 直接上一跳：FactualMemory.id 或另一条 ReconstructiveMemory.id
    reconstructed_fact: str  # 经过情绪滤镜后可能扭曲的版本
    trigger:            str  # 触发重构的上下文描述


# ── Narrative Memory ──────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class NarrativeMemory(MemoryUnit):
    """叙述性漂移记忆：由 LifeManager 产出，编织 Agent 的人生叙事。

    不记录单一事件，而是将若干事实性/重构型记忆整合为一段连贯叙事。
    `narrative` 随每次 LifeManager 重新叙述而产生微妙"漂移"。
    `source_ids` 指向参与编织这段叙事的记忆单元 id。
    `chapter` 是人生章节标签（如"与用户建立信任的早期阶段"），
    供跨章节检索和叙事连贯性维护使用。

    叙述性记忆天然驻留长期记忆层（`__post_init__` 强制设定）。

    示例
    ----
        NarrativeMemory(
            focus      = "早期架构探索阶段",
            narrative  = "在协作的最初阶段，我们经历了多次关于模块边界的讨论...",
            source_ids = ["<id1>", "<id2>"],
            chapter    = "系统构建早期",
            emotion            = "好奇",
            emotion_intensity  = 0.5,
            valence            = Valence.positive,
        )
    """

    MEMORY_TYPE = "narrative"

    narrative:  str       = ""                        # 叙事段落（LifeManager 生成）
    source_ids: list[str] = field(default_factory=list)  # 涉及的记忆单元 id
    chapter:    str       = ""                        # 人生章节标签

    def __post_init__(self) -> None:
        self.tier = MemoryTier.long  # 叙述性记忆始终驻留长期记忆层
