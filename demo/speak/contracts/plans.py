from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .protocols import ShareEventLike

GateAction = Literal["listen", "speak", "hold", "brew"]
Continuity = Literal["append", "finish"]
TurnTrigger = Literal["user", "poll"]
ShareTag = Literal["none", "share", "expand"]


@dataclass(frozen=True)
class RhythmSegment:
    wait_reason: str = ""
    continuity: Continuity = "finish"


@dataclass(frozen=True)
class RhythmPlan:
    """
    开口计划：gate / share_tag 为指令编码；
    mood / cue / tempo / reply_guide / reason 为自然语言。
    吐字时序由 reply 打字机负责。
    """

    gate: GateAction
    segments: tuple[RhythmSegment, ...]
    continuity: Continuity = "finish"
    cue: str = ""
    tempo: str = ""
    reply_guide: str = ""
    reason: str = ""
    mood: str = ""
    share_tag: ShareTag = "none"
    share_id: str = ""

    @property
    def should_speak(self) -> bool:
        return self.gate in ("speak", "brew") and bool(self.segments)

    @property
    def wants_share(self) -> bool:
        return self.share_tag in ("share", "expand")

    def snapshot(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "continuity": self.continuity,
            "cue": self.cue,
            "tempo": self.tempo,
            "reply_guide": self.reply_guide,
            "reason": self.reason,
            "mood": self.mood,
            "share_tag": self.share_tag,
            "share_id": self.share_id,
            "segments": [
                {
                    "wait_reason": seg.wait_reason,
                    "continuity": seg.continuity,
                }
                for seg in self.segments
            ],
        }


@dataclass(frozen=True)
class ShareHandOff:
    """rhythm → compose 的单条分享交接；不含队列拷贝。"""

    tag: ShareTag
    event: ShareEventLike | None = None
    expand_text: str = ""

    @property
    def active(self) -> bool:
        return self.tag != "none" and self.event is not None

    def material_line(self) -> str:
        if self.event is None:
            return ""
        body = self.event.one_line()
        if self.tag == "expand" and self.expand_text.strip():
            return f"{body}\n见闻展开：{self.expand_text.strip()}"
        if self.tag == "expand":
            return f"{body}\n（展开检索尚未接线，先用条目本身）"
        return body


@dataclass(frozen=True)
class ComposeBundle:
    """拼接导演产出：供给回复导演的 system 材料（按临场 recipe 裁剪）。"""

    session_id: str
    turn_index: int
    persona_block: str
    presence_block: str = ""
    portrait_block: str = ""
    on_scene_block: str = ""
    memory_hint: str = ""
    journal_block: str = ""
    context_block: str = ""
    scene_block: str = ""
    mood_block: str = ""
    include_portrait: bool = True
    include_memory: bool = True
    include_architecture_note: bool = True
    proactive: bool = False
    share_title: str = ""
    notes: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "include_portrait": self.include_portrait,
            "include_memory": self.include_memory,
            "include_architecture_note": self.include_architecture_note,
            "proactive": self.proactive,
            "share_title": self.share_title,
            "on_scene": self.on_scene_block[:120],
            "notes": list(self.notes),
            "persona_preview": self.persona_block[:120],
        }


@dataclass(frozen=True)
class FilledSegment:
    text: str
    wait_reason: str = ""
    continuity: Continuity = "finish"


@dataclass(frozen=True)
class TurnResult:
    session_id: str
    turn_index: int
    trigger: TurnTrigger
    user_text: str
    rhythm: RhythmPlan
    bundle: ComposeBundle | None
    segments: tuple[FilledSegment, ...]
    answer: str
    notes: tuple[str, ...] = ()
    stage: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "trigger": self.trigger,
            "user_text": self.user_text,
            "rhythm": self.rhythm.snapshot(),
            "bundle": None if self.bundle is None else self.bundle.snapshot(),
            "answer": self.answer,
            "stage": self.stage,
            "segments": [
                {
                    "text": seg.text,
                    "wait_reason": seg.wait_reason,
                    "continuity": seg.continuity,
                }
                for seg in self.segments
            ],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class PollTickResult:
    poll_index: int
    idle_ms: int
    rhythm: RhythmPlan
    spoke: bool
    turn: TurnResult | None = None
    stage: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "poll_index": self.poll_index,
            "idle_ms": self.idle_ms,
            "spoke": self.spoke,
            "rhythm": self.rhythm.snapshot(),
            "stage": self.stage,
            "turn": None if self.turn is None else self.turn.snapshot(),
        }
