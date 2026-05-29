from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ExperienceActionKind(str, Enum):
    attending   = "attending"    # 感知/注意——被动接收即已构成行动
    reasoning   = "reasoning"    # 内部推理
    speaking    = "speaking"     # 向用户产出
    tool_use    = "tool_use"     # 执行工具
    remembering = "remembering"  # 检索记忆
    deciding    = "deciding"     # 做出判断或选择


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# ── 情境 ──────────────────────────────────────────────────────────────────────

@dataclass
class ExperienceSituation:
    """此刻的世界状态快照：Agent 感知到体验时所处的外部与内在背景。

    四个部分：
    - `perception`    — Agent 对环境的感知和描述（感知到了什么）
    - `narration`     — Agent 对这个事件的叙述（如何框架化这件事）
    - `prior_thought` — 体验发生前已有的思维背景（预设、期待、担忧）
    - `activated_memory_ids` — 体验瞬间已被激活的记忆 id 快照
    """
    session_id:           str       = ""
    turn_index:           int       = 0
    perception:           str       = ""   # 对环境的感知和描述
    narration:            str       = ""   # 对这个事件的叙述与框架化
    prior_thought:        str       = ""   # 体验前的思维底色（非推理行为，是背景）
    activated_memory_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id":           self.session_id,
            "turn_index":           self.turn_index,
            "perception":           self.perception,
            "narration":            self.narration,
            "prior_thought":        self.prior_thought,
            "activated_memory_ids": self.activated_memory_ids,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExperienceSituation:
        return cls(
            session_id=d.get("session_id", ""),
            turn_index=int(d.get("turn_index", 0)),
            perception=d.get("perception", ""),
            narration=d.get("narration", ""),
            prior_thought=d.get("prior_thought", ""),
            activated_memory_ids=d.get("activated_memory_ids", []),
        )


# ── 行动 ──────────────────────────────────────────────────────────────────────

@dataclass
class ExperienceAction:
    """Agent 在此体验中实际发生的行为——身体或心智层面均算。

    `kind` 是行为分类；`content` 是对该行为的可读描述，
    不要求完整还原输出内容，只需足以事后指认。
    """
    kind:    ExperienceActionKind
    content: str = ""

    def to_dict(self) -> dict:
        return {
            "kind":    self.kind.value,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExperienceAction:
        return cls(
            kind=ExperienceActionKind(d.get("kind", "attending")),
            content=d.get("content", ""),
        )


# ── 感受 ──────────────────────────────────────────────────────────────────────

@dataclass
class ExperienceFeeling:
    """体验发生瞬间的状态差分——不是事后标注，而是当下变化量。

    `valence_delta` / `arousal_delta` 即时连续产生，供心跳漂移和记忆激活使用。
    `emotion_label` 即时填充：体验发生时由调用方直接给出命名情绪，不依赖事后回填。
    """
    valence_delta: float = 0.0   # 负值 = 向负向漂移，正值 = 向正向漂移
    arousal_delta: float = 0.0   # 负值 = 平静化，正值 = 唤醒增强
    salience:      float = 0.0   # 显著性标量（由自叙投影，供记账与展示）
    emotion_label: str   = ""    # 命名情绪，惰性回填
    salience_note: str   = ""    # agent 显著性/感受自叙原文（擢升判定主依据）

    def to_dict(self) -> dict:
        return {
            "valence_delta": self.valence_delta,
            "arousal_delta": self.arousal_delta,
            "salience":      self.salience,
            "emotion_label": self.emotion_label,
            "salience_note": self.salience_note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExperienceFeeling:
        return cls(
            valence_delta=float(d.get("valence_delta", 0.0)),
            arousal_delta=float(d.get("arousal_delta", 0.0)),
            salience=float(d.get("salience", 0.0)),
            emotion_label=d.get("emotion_label", ""),
            salience_note=d.get("salience_note", ""),
        )


# ── 主体 ──────────────────────────────────────────────────────────────────────

@dataclass
class ExperienceUnit:
    """最小生命体验单元：情境 + 行动 + 感受 的不可再分绑定。

    构成条件：
    - 有边界的连续意识切片（`ts` 锚定起始）
    - 三要素同时在场（缺任何一个不构成完整体验）
    - 事后可由 `id` 指认（支持记忆与叙事引用）

    `source` 标记体验的触发来源：
    - ``"user"``       — 来自用户输入
    - ``"narrative"``  — 来自地标填充（手账叙事引擎）
    - ``"heartbeat"``  — 来自心跳漫游
    - ``"collision"``  — 用户体验与叙事体验交会折叠后的新体验
    - ``"task"``       — 来自调度器任务
    - ``"system"``     — 系统内部触发
    """
    situation: ExperienceSituation
    action:    ExperienceAction
    feeling:   ExperienceFeeling
    ts:        str = field(default_factory=_now_iso)
    source:    str = ""
    id:        str = field(default_factory=_uid)

    def should_promote_to_memory(self) -> bool:
        from .memory_promotion import should_promote_to_memory

        return should_promote_to_memory(self)

    def is_salient(self, threshold: float | None = None) -> bool:
        _ = threshold
        return self.should_promote_to_memory()

    @staticmethod
    def make(
        situation: ExperienceSituation,
        action:    ExperienceAction,
        feeling:   ExperienceFeeling,
        source:    str = "",
    ) -> ExperienceUnit:
        return ExperienceUnit(
            situation=situation,
            action=action,
            feeling=feeling,
            source=source,
        )

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "ts":        self.ts,
            "source":    self.source,
            "situation": self.situation.to_dict(),
            "action":    self.action.to_dict(),
            "feeling":   self.feeling.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExperienceUnit:
        return cls(
            id=d.get("id", _uid()),
            ts=d.get("ts", _now_iso()),
            source=d.get("source", ""),
            situation=ExperienceSituation.from_dict(d.get("situation", {})),
            action=ExperienceAction.from_dict(d.get("action", {})),
            feeling=ExperienceFeeling.from_dict(d.get("feeling", {})),
        )
