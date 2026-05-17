from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventType(str, Enum):
    """事件类型——描述"发生了什么类型的事"，不含情感判断。"""
    INTERACTION = "interaction"     # 与用户的一次对话
    TASK        = "task"            # 完成了一个调度任务
    THOUGHT     = "thought"         # 内部浮现的念头（未付诸行动）
    MILESTONE   = "milestone"       # 值得标记的节点（首次、完成某类目标等）
    CREATIVE    = "creative"        # 创作类输出（写作、生成等）


@dataclass
class LifeEvent:
    """基本事件单元——严格事实性质，不含任何情感解读。

    设计原则
    --------
    - description 必须是事实陈述，使用动词短语，避免情感词
      ✓ "完成了关于量子计算的问答，涉及 5 轮交流"
      ✗ "今天的量子计算讨论让人感到兴奋"
    - 情感判断由 status 层（StatusSynthesizer）负责
    - 可扩展字段放入 metadata，不改变核心结构

    字段
    ----
    ts          : 事件发生时间（ISO 8601 UTC）
    event_type  : 事件类型（EventType 枚举）
    description : 事实描述（动词短语，不含情感词）
    source      : 来源标识（任务名、会话 ID 等，可为空）
    duration_min: 持续时长（分钟），0 表示未知或瞬时
    metadata    : 可扩展的额外字段
    """
    ts: str
    event_type: EventType
    description: str
    source: str = ""
    duration_min: int = 0
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @staticmethod
    def now(
        event_type: EventType,
        description: str,
        source: str = "",
        duration_min: int = 0,
        **metadata,
    ) -> LifeEvent:
        return LifeEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            description=description,
            source=source,
            duration_min=duration_min,
            metadata=metadata,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "event_type": self.event_type.value,
            "description": self.description,
            "source": self.source,
            "duration_min": self.duration_min,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LifeEvent:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            ts=d.get("ts", ""),
            event_type=EventType(d.get("event_type", "interaction")),
            description=d.get("description", ""),
            source=d.get("source", ""),
            duration_min=int(d.get("duration_min", 0)),
            metadata=d.get("metadata", {}),
        )

    def to_fact_line(self) -> str:
        """渲染为单行事实陈述，供 StatusSynthesizer 使用。"""
        prefix = f"[{self.event_type.value}]"
        suffix = f"（{self.duration_min}分钟）" if self.duration_min > 0 else ""
        return f"{prefix} {self.description}{suffix}"
