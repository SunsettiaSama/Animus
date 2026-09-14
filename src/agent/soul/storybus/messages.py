"""storybus.messages — 剧情通信消息数据类（协议 v1.2，纯 dataclass）。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BeatAckStatus(str, Enum):
    """演出回执五态（协议 §7.3）。

    - performed：已演出（终态，life 推进 landmark 并 sync 进度）
    - expired：过保鲜期未演（终态，归档为"错过的剧情"）
    - declined：角色拒演（终态，归档）
    - silenced：角色选择沉默（非终态，life 可改期或归档）
    - suppressed：用户在忙被抑制（非终态，life 改期）
    """

    performed = "performed"
    expired = "expired"
    declined = "declined"
    silenced = "silenced"
    suppressed = "suppressed"


class BeatKind(str, Enum):
    landmark_progress = "landmark_progress"
    agenda_due = "agenda_due"
    incident = "incident"
    chronicle_echo = "chronicle_echo"


@dataclass(frozen=True)
class PerformanceHint:
    """建议性表演提示——开口时机由角色自决（R7），这不是指令。"""

    urgency: str = "normal"           # calm | normal | eager
    share_desire: float = 0.5         # 0~1 想说的欲望强度
    valid_until: str = ""             # ISO ts；空 = 不设保鲜期


@dataclass(frozen=True)
class BeatProvenance:
    """溯源：ack(performed) 后 life 用于推进 landmark/chronicle。"""

    landmark_id: str = ""
    agenda_id: str = ""
    source_tick: str = ""


@dataclass(frozen=True)
class LifeStoryBeat:
    """life → speak：给角色的"想说的话"。"""

    beat_id: str
    narrative: str
    channels: tuple[str, ...] = ()
    card_id: str = ""                  # 所属剧情弧/卡片；空 = 独立事件
    kind: str = BeatKind.landmark_progress.value
    hint: PerformanceHint = field(default_factory=PerformanceHint)
    provenance: BeatProvenance = field(default_factory=BeatProvenance)
    cached: bool = False               # true = 来自预跑缓存（R9），消费零等待
    created_at: str = field(default_factory=_now_iso)

    def is_expired(self, *, now: float | None = None) -> bool:
        until = self.hint.valid_until
        if not until:
            return False
        try:
            deadline = datetime.fromisoformat(until)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            epoch = now if now is not None else time.time()
            return deadline.timestamp() <= epoch
        except ValueError:
            return False

    def to_payload(self) -> dict[str, Any]:
        """WS 出站载荷形态（speak io / 前端帧复用）。"""
        return {
            "beat_id": self.beat_id,
            "card_id": self.card_id,
            "channels": list(self.channels),
            "kind": self.kind,
            "narrative": self.narrative,
            "hint": {
                "urgency": self.hint.urgency,
                "share_desire": self.hint.share_desire,
                "valid_until": self.hint.valid_until,
            },
            "cached": self.cached,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class BeatDraft:
    """导演/编剧产出的待投递稿（outbox 负责补 id/时间并投递）。"""

    narrative: str
    channels: tuple[str, ...] = ()
    card_id: str = ""
    kind: str = BeatKind.landmark_progress.value
    hint: PerformanceHint = field(default_factory=PerformanceHint)
    provenance: BeatProvenance = field(default_factory=BeatProvenance)
    cached: bool = False

    def with_beat_id(self, beat_id: str) -> LifeStoryBeat:
        return LifeStoryBeat(
            beat_id=beat_id,
            narrative=self.narrative,
            channels=self.channels,
            card_id=self.card_id,
            kind=self.kind,
            hint=self.hint,
            provenance=self.provenance,
            cached=self.cached,
        )


@dataclass(frozen=True)
class StoryProgressSync:
    """life → speak：剧情卡片进度段刷新（高频、可合并、无 ack、丢帧无害）。"""

    card_id: str
    current: str
    upcoming: tuple[str, ...] = ()    # 预告不是承诺，可随演绎改变
    updated_at: str = field(default_factory=_now_iso)


@dataclass(frozen=True)
class StorySignal:
    """speak → life：用户轮信号（供导演做缓存失效判定，R9）。"""

    session_id: str
    channel: str
    turn_digest: str                  # 摘要非全文，控制信息量
    salience_hint: float = 0.3
    at: str = field(default_factory=_now_iso)


@dataclass(frozen=True)
class BeatAck:
    """speak/角色 → life：演出回执（按渠道分别回）。"""

    beat_id: str
    channel: str
    status: BeatAckStatus | str
    performed_at: str = field(default_factory=_now_iso)

    def status_value(self) -> str:
        return self.status.value if isinstance(self.status, BeatAckStatus) else str(self.status)


@dataclass(frozen=True)
class StoryCard:
    """剧情卡片双段模型（R8）：大纲段冻结 + 进度段实时。"""

    card_id: str
    outline: str                       # 冻结段：编剧交稿后不变
    current: str = ""                 # 进度段：当前演绎进度
    upcoming: tuple[str, ...] = ()    # 进度段：之后的演绎进度（预告）
    updated_at: str = field(default_factory=_now_iso)

    @staticmethod
    def new_id() -> str:
        return f"card-{uuid.uuid4().hex[:12]}"
