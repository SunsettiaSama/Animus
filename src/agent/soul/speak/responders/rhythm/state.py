from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .contracts import OnSceneState, RhythmAffect, RhythmReview, ShareItem

GATE_STREAK_WARN = 3
GATE_STREAK_SEVERE = 5


@dataclass(frozen=True)
class HistoryBeat:
    speaker: str
    text: str

    def one_line(self, *, limit: int = 80) -> str:
        body = " ".join(self.text.strip().split())
        if len(body) > limit:
            body = body[: limit - 1] + "…"
        return f"{self.speaker}:{body}"

    def snapshot(self) -> dict[str, Any]:
        return {"speaker": self.speaker, "text": self.text}


@dataclass(frozen=True)
class DirectorLogBeat:
    trigger: str
    gate: str
    cue: str = ""
    tempo: str = ""
    reply_guide: str = ""
    reason: str = ""
    spoke: bool = False

    def one_line(self, *, limit: int = 120) -> str:
        body = (
            f"[导演][{self.trigger}] gate={self.gate} "
            f"spoke={self.spoke} cue={self.cue} tempo={self.tempo} "
            f"guide={self.reply_guide} reason={self.reason}"
        )
        body = " ".join(body.split())
        if len(body) > limit:
            return body[: limit - 1] + "…"
        return body

    def snapshot(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "gate": self.gate,
            "cue": self.cue,
            "tempo": self.tempo,
            "reply_guide": self.reply_guide,
            "reason": self.reason,
            "spoke": self.spoke,
        }


def gate_streak_warning(gate: str, streak: int) -> str:
    token = gate.strip() or "?"
    if streak >= GATE_STREAK_SEVERE:
        return (
            f"【严重警告】你已连续 {streak} 次采用同一指令 gate={token}。"
            f"请停一下自问：是否真的决定继续 {token}？"
            "若对话弧 / 待分享 / 用户留白在催开口，应改 brew 或 speak；"
            f"若坚持 {token}，必须在 reason 里写清「为什么这一拍仍不能改」。"
        )
    if streak >= GATE_STREAK_WARN:
        return (
            f"【警告】你已连续 {streak} 次采用同一指令 gate={token}。"
            "请审视这一决定是否僵住了：材料变了没有？该听还是该轻声补一句？"
            f"不要只因为上一拍也是 {token} 就惯性复读。"
        )
    return ""


@dataclass
class RhythmSessionState:
    session_id: str
    arc_text: str = ""
    review: RhythmReview = field(default_factory=RhythmReview)
    affect: RhythmAffect = field(default_factory=RhythmAffect)
    on_scene: OnSceneState = field(default_factory=OnSceneState)
    beats_since_affect: int = 0
    beats_since_on_scene: int = 0
    last_gate: str = ""
    gate_streak: int = 0
    last_shared: ShareItem | None = None
    history: list[HistoryBeat] = field(default_factory=list)
    director_log: list[DirectorLogBeat] = field(default_factory=list)
    beat_index: int = 0
    inited: bool = False

    @property
    def last_shared_id(self) -> str:
        if self.last_shared is None:
            return ""
        return self.last_shared.item_id

    def note_gate(self, gate: str) -> int:
        token = gate.strip()
        if token and token == self.last_gate:
            self.gate_streak += 1
        else:
            self.last_gate = token
            self.gate_streak = 1 if token else 0
        return self.gate_streak

    def mark_rhythm_beat(self) -> None:
        self.beat_index += 1
        self.beats_since_affect += 1
        self.beats_since_on_scene += 1

    def mark_affect_refreshed(self) -> None:
        self.beats_since_affect = 0

    def mark_on_scene_refreshed(self) -> None:
        self.beats_since_on_scene = 0

    def set_affect(
        self,
        *,
        label: str | None = None,
        valence: str | None = None,
        intensity: float | None = None,
    ) -> None:
        if label is not None:
            self.affect.label = label.strip() or self.affect.label
        if valence is not None:
            token = valence.strip().lower()
            if token in ("positive", "neutral", "negative", "mixed"):
                self.affect.valence = token  # type: ignore[assignment]
        if intensity is not None:
            self.affect.intensity = float(intensity)
        self.affect.clamp()

    def set_on_scene(self, state: OnSceneState) -> None:
        self.on_scene = state
        self.mark_on_scene_refreshed()

    def set_review(self, review: RhythmReview) -> None:
        self.review = review

    def set_arc(self, text: str) -> None:
        self.arc_text = text.strip()
        self.inited = True

    def append_history(self, speaker: str, text: str, *, keep: int = 24) -> None:
        body = text.strip()
        if not body:
            return
        self.history.append(HistoryBeat(speaker=speaker, text=body))
        if len(self.history) > keep:
            self.history = self.history[-keep:]

    def record_director(self, beat: DirectorLogBeat, *, keep: int = 32) -> None:
        self.director_log.append(beat)
        self.note_gate(beat.gate)
        if len(self.director_log) > keep:
            self.director_log = self.director_log[-keep:]

    def recent_history(self, limit: int = 8) -> tuple[HistoryBeat, ...]:
        return tuple(self.history[-limit:])

    def recent_directors(self, limit: int = 6) -> tuple[DirectorLogBeat, ...]:
        return tuple(self.director_log[-limit:])

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "arc_text": self.arc_text,
            "review": self.review.snapshot(),
            "affect": self.affect.snapshot(),
            "on_scene": self.on_scene.snapshot(),
            "beats_since_affect": self.beats_since_affect,
            "beats_since_on_scene": self.beats_since_on_scene,
            "last_gate": self.last_gate,
            "gate_streak": self.gate_streak,
            "last_shared_id": self.last_shared_id,
            "last_shared": None
            if self.last_shared is None
            else self.last_shared.snapshot(),
            "history": [item.snapshot() for item in self.history[-8:]],
            "director_log": [item.snapshot() for item in self.director_log[-6:]],
            "beat_index": self.beat_index,
            "inited": self.inited,
        }


class RhythmStateStore:
    """Per-session rhythm state; in-memory only for v1."""

    def __init__(self) -> None:
        self._states: dict[str, RhythmSessionState] = {}
        self._lock = threading.Lock()

    def session(self, session_id: str) -> RhythmSessionState:
        sid = session_id.strip()
        with self._lock:
            if sid not in self._states:
                self._states[sid] = RhythmSessionState(session_id=sid)
            return self._states[sid]

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._lock:
            self._states.pop(sid, None)

    def snapshot(self, session_id: str) -> dict[str, Any]:
        return self.session(session_id).snapshot()
