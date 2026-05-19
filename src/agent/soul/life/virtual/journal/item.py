from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# Agent 每天最多写入的地标数量
MAX_DAILY_LANDMARKS: int = 3

# 编排新地标时注入的历史地标上限
K_RECENT_LANDMARKS: int = 5


class LandmarkStatus(str, Enum):
    pending    = "pending"    # 已写下，等待触发时间
    processing = "processing" # API 请求进行中
    done       = "done"       # 情节已填充，体验已内化
    overdue    = "overdue"    # 已超时但尚未处理（服务重启后发现）


@dataclass
class Landmark:
    """手账地标——Agent 预约的一次叙事体验。

    生命周期
    --------
    1. Agent 写下意图（``intention``）并设定触发时间（``scheduled_at``）
    2. 到点后（或重启发现超时），``LandmarkFiller`` 拿到三路输入：
       - agent 画像（PersonaProfile / LifeProfile）
       - 记忆检索结果
       - 近 ``K_RECENT_LANDMARKS`` 个历史地标
       → 调用一次 API → 填入完整情节（``narrative``）
    3. 情节被 ``ExperienceBuilder.record_story_beat()`` 内化为
       ``ExperienceUnit``，``experience_id`` 回填至本地标

    字段语义
    --------
    - ``intention``    — 意图描述（Agent 自己写，一句话）
    - ``scheduled_at`` — 预定触发时间（ISO 8601）
    - ``status``       — 当前状态
    - ``narrative``    — 填充后的完整情节文本（由 API 生成）
    - ``experience_id``— 关联的 ExperienceUnit.id（内化后回填）
    - ``context``      — 触发条件或背景备注（可空）
    """
    intention:     str
    scheduled_at:  str
    id:            str            = field(default_factory=_uid)
    created_at:    str            = field(default_factory=_now_iso)
    status:        LandmarkStatus = LandmarkStatus.pending
    narrative:     str            = ""
    experience_id: str            = ""
    context:       str            = ""
    dice_value:    int            = 0   # 填充时的命运骰点（0 表示尚未投掷）
    dice_tendency: str            = ""  # 骰点对应的倾向描述

    # ── 状态转换 ──────────────────────────────────────────────────────────────

    def mark_processing(self) -> None:
        self.status = LandmarkStatus.processing

    def mark_done(
        self,
        narrative: str,
        experience_id: str = "",
        dice_value: int = 0,
        dice_tendency: str = "",
    ) -> None:
        self.status        = LandmarkStatus.done
        self.narrative     = narrative
        if experience_id:
            self.experience_id = experience_id
        if dice_value:
            self.dice_value   = dice_value
            self.dice_tendency = dice_tendency

    def mark_overdue(self) -> None:
        if self.status == LandmarkStatus.pending:
            self.status = LandmarkStatus.overdue

    # ── 时间判断 ──────────────────────────────────────────────────────────────

    def is_due(self) -> bool:
        """触发时间已到（或已超时），且尚未处理。"""
        if self.status not in (LandmarkStatus.pending, LandmarkStatus.overdue):
            return False
        scheduled = datetime.fromisoformat(self.scheduled_at)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= scheduled

    def is_overdue(self) -> bool:
        return self.status == LandmarkStatus.overdue

    # ── 序列化 ────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "intention":     self.intention,
            "scheduled_at":  self.scheduled_at,
            "created_at":    self.created_at,
            "status":        self.status.value,
            "narrative":     self.narrative,
            "experience_id": self.experience_id,
            "context":       self.context,
            "dice_value":    self.dice_value,
            "dice_tendency": self.dice_tendency,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Landmark:
        return cls(
            id=            d.get("id", _uid()),
            intention=     d["intention"],
            scheduled_at=  d["scheduled_at"],
            created_at=    d.get("created_at", _now_iso()),
            status=        LandmarkStatus(d.get("status", "pending")),
            narrative=     d.get("narrative", ""),
            experience_id= d.get("experience_id", ""),
            context=       d.get("context", ""),
            dice_value=    d.get("dice_value", 0),
            dice_tendency= d.get("dice_tendency", ""),
        )
