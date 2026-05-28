from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..types import SessionEndReason, SessionEndResult, SessionLifecyclePort


SPEAK_SESSION_IDLE_SEC = 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SpeakSessionRecord:
    session_id: str
    generation: int = 1
    turn_index: int = 0
    opened_at: datetime = field(default_factory=_utcnow)
    last_activity_at: datetime = field(default_factory=_utcnow)


class SpeakSessionRegistry:
    """Speak 会话持有：物理 idle 检测与 generation 记录。"""

    def __init__(
        self,
        *,
        idle_sec: float = SPEAK_SESSION_IDLE_SEC,
        lifecycle: SessionLifecyclePort | None = None,
        touch_dialogue: Callable[[str], None] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        on_temporal_expire: Callable[[str], SessionEndResult] | None = None,
    ) -> None:
        self._idle_sec = idle_sec
        self._lifecycle = lifecycle
        self._touch_dialogue = touch_dialogue
        self._now_fn = now_fn or _utcnow
        self._on_temporal_expire = on_temporal_expire
        self._records: dict[str, SpeakSessionRecord] = {}
        self._interactors: dict[str, str] = {}

    def bind_interactor(self, session_id: str, interactor_id: str) -> None:
        resolved = interactor_id.strip() or session_id.strip()
        if resolved:
            self._interactors[session_id] = resolved

    def get_interactor(self, session_id: str) -> str:
        bound = self._interactors.get(session_id, "").strip()
        if bound:
            return bound
        return session_id.strip() or "default"

    @property
    def lifecycle(self) -> SessionLifecyclePort | None:
        return self._lifecycle

    @property
    def idle_sec(self) -> float:
        return self._idle_sec

    def get(self, session_id: str) -> SpeakSessionRecord:
        record = self._records.get(session_id)
        if record is None:
            record = SpeakSessionRecord(session_id=session_id)
            self._records[session_id] = record
        return record

    def is_temporally_expired(self, session_id: str, *, now: datetime | None = None) -> bool:
        record = self.get(session_id)
        current = now or self._now_fn()
        elapsed = (current - record.last_activity_at).total_seconds()
        return elapsed > self._idle_sec

    def ensure_active(self, session_id: str) -> tuple[SpeakSessionRecord, bool]:
        """确保会话活跃；idle 超时则 finalize。返回 (record, temporal_rotated)。"""
        now = self._now_fn()
        if self.is_temporally_expired(session_id, now=now) and self._on_temporal_expire is not None:
            self._on_temporal_expire(session_id)
            return self.get(session_id), True

        record = self.get(session_id)
        if self._touch_dialogue is not None:
            self._touch_dialogue(session_id)
        record.last_activity_at = now
        return record, False

    def touch(self, session_id: str) -> SpeakSessionRecord:
        record = self.get(session_id)
        now = self._now_fn()
        if self._touch_dialogue is not None:
            self._touch_dialogue(session_id)
        record.last_activity_at = now
        return record

    def begin_turn(self, session_id: str) -> int:
        record = self.get(session_id)
        record.turn_index += 1
        return record.turn_index

    def current_turn_index(self, session_id: str) -> int:
        return self.get(session_id).turn_index

    def rotate_generation(self, session_id: str, *, now: datetime | None = None) -> SpeakSessionRecord:
        record = self.get(session_id)
        current = now or self._now_fn()
        record = SpeakSessionRecord(
            session_id=session_id,
            generation=record.generation + 1,
            turn_index=0,
            opened_at=current,
            last_activity_at=current,
        )
        self._records[session_id] = record
        return record
