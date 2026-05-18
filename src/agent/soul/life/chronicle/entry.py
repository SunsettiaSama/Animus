from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class ChronicleKind(str, Enum):
    user_turn   = "user_turn"
    story_beat  = "story_beat"
    landmark    = "landmark"   # 地标被填充并内化为体验单元


@dataclass
class ChronicleEntry:
    """一条已完成事件的客观事实记录。

    `ChronicleEntry` 是永久性的（不会被 purge），区别于 `ExperienceUnit`
    的热存储（有时间窗口）。它回答"发生了什么"，而不是"Agent 感受到了什么"。

    字段语义
    --------
    - `kind`          — 事件类型：用户回合 / 故事节拍
    - `summary`       — 一句话客观摘要
    - `session_id`    — 所属会话 ID（user_turn 适用）
    - `turn_index`    — 回合序号（user_turn 适用）
    - `emotion_label` — 情绪标签（可空）
    - `salience`      — 显著性（0-1），供大纲综合时加权
    - `experience_id` — 关联的 ExperienceUnit ID（可选，用于追溯）
    """
    kind:          ChronicleKind
    summary:       str
    id:            str   = field(default_factory=_uid)
    ts:            str   = field(default_factory=_now_iso)
    session_id:    str   = ""
    turn_index:    int   = 0
    emotion_label: str   = ""
    salience:      float = 0.0
    experience_id: str   = ""

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "ts":           self.ts,
            "kind":         self.kind.value,
            "summary":      self.summary,
            "session_id":   self.session_id,
            "turn_index":   self.turn_index,
            "emotion_label":self.emotion_label,
            "salience":     self.salience,
            "experience_id":self.experience_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ChronicleEntry:
        return cls(
            id=           d.get("id", _uid()),
            ts=           d.get("ts", _now_iso()),
            kind=         ChronicleKind(d["kind"]),
            summary=      d.get("summary", ""),
            session_id=   d.get("session_id", ""),
            turn_index=   d.get("turn_index", 0),
            emotion_label=d.get("emotion_label", ""),
            salience=     d.get("salience", 0.0),
            experience_id=d.get("experience_id", ""),
        )
