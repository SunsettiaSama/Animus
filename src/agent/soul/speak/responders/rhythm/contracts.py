from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

GateAction = Literal["listen", "speak", "hold", "brew"]
Continuity = Literal["append", "finish"]
ShareTag = Literal["none", "share", "expand"]
OnSceneFocus = Literal["present", "drift", "notice"]
AffectValence = Literal["positive", "neutral", "negative", "mixed"]


@dataclass(frozen=True)
class RhythmSegment:
    wait_reason: str = ""
    continuity: Continuity = "finish"

    def snapshot(self) -> dict[str, Any]:
        return {
            "wait_reason": self.wait_reason,
            "continuity": self.continuity,
        }


@dataclass(frozen=True)
class RhythmPlan:
    gate: GateAction
    segments: tuple[RhythmSegment, ...] = ()
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
            "segments": [seg.snapshot() for seg in self.segments],
        }


@dataclass(frozen=True)
class RhythmReview:
    abstract: str = ""
    summary: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.abstract.strip() or self.summary.strip())

    def snapshot(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "summary": self.summary,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RhythmReview:
        return cls(
            abstract=str(payload.get("abstract") or "").strip(),
            summary=str(payload.get("summary") or "").strip(),
        )


@dataclass
class RhythmAffect:
    label: str = "平静"
    valence: AffectValence = "neutral"
    intensity: float = 0.0

    def clamp(self) -> None:
        self.intensity = max(0.0, min(1.0, float(self.intensity)))

    def snapshot(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "valence": self.valence,
            "intensity": self.intensity,
        }


@dataclass
class OnSceneState:
    text: str = ""
    focus: OnSceneFocus = "present"
    beat_index: int = 0

    @property
    def ready(self) -> bool:
        return bool(self.text.strip())

    def one_line(self, *, limit: int = 80) -> str:
        body = " ".join(self.text.strip().split())
        if len(body) > limit:
            body = body[: limit - 1] + "…"
        return body

    def snapshot(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "focus": self.focus,
            "beat_index": self.beat_index,
        }


@dataclass(frozen=True)
class ShareItem:
    item_id: str
    topic: str
    detail: str = ""
    source: str = ""
    salience: float = 0.0

    def one_line(self) -> str:
        base = self.topic.strip()
        if self.detail.strip():
            return f"{base}（{self.detail.strip()[:80]}）"
        return base

    def snapshot(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "topic": self.topic,
            "detail": self.detail,
            "source": self.source,
            "salience": self.salience,
        }


@dataclass(frozen=True)
class ShareHandOff:
    tag: ShareTag
    item: ShareItem | None = None
    expand_text: str = ""
    queue_index: int | None = None

    @property
    def active(self) -> bool:
        return self.tag != "none" and self.item is not None

    def material_line(self) -> str:
        if self.item is None:
            return ""
        body = self.item.one_line()
        if self.tag == "expand" and self.expand_text.strip():
            return f"{body}\n见闻展开：{self.expand_text.strip()}"
        if self.tag == "expand":
            return f"{body}\n（展开检索尚未接线，先用条目本身）"
        return body

    def snapshot(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "item": None if self.item is None else self.item.snapshot(),
            "expand_text": self.expand_text,
            "queue_index": self.queue_index,
        }
