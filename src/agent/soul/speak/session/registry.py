from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol


SPEAK_SESSION_IDLE_SEC = 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SpeakSessionRecord:
    session_id: str
    generation: int = 1
    opened_at: datetime = field(default_factory=_utcnow)
    last_activity_at: datetime = field(default_factory=_utcnow)


class SessionLifecyclePort(Protocol):
    def close_dialogue_interaction(self, session_id: str) -> dict: ...
    def start_dialogue_session(self, session_id: str) -> dict: ...


class SpeakSessionRegistry:
    """Speak 会话持有与 1h 硬超时。"""

    def __init__(
        self,
        *,
        idle_sec: float = SPEAK_SESSION_IDLE_SEC,
        lifecycle: SessionLifecyclePort | None = None,
        touch_dialogue: Callable[[str], None] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._idle_sec = idle_sec
        self._lifecycle = lifecycle
        self._touch_dialogue = touch_dialogue
        self._now_fn = now_fn or _utcnow
        self._records: dict[str, SpeakSessionRecord] = {}

    def get(self, session_id: str) -> SpeakSessionRecord:
        record = self._records.get(session_id)
        if record is None:
            record = SpeakSessionRecord(session_id=session_id)
            self._records[session_id] = record
        return record

    def ensure_active(self, session_id: str) -> SpeakSessionRecord:
        record = self.get(session_id)
        now = self._now_fn()
        elapsed = (now - record.last_activity_at).total_seconds()
        if elapsed > self._idle_sec and self._lifecycle is not None:
            self._lifecycle.close_dialogue_interaction(session_id)
            self._lifecycle.start_dialogue_session(session_id)
            record = SpeakSessionRecord(
                session_id=session_id,
                generation=record.generation + 1,
                opened_at=now,
                last_activity_at=now,
            )
            self._records[session_id] = record
            return record

        if self._touch_dialogue is not None:
            self._touch_dialogue(session_id)
        record.last_activity_at = now
        return record

    def touch(self, session_id: str) -> SpeakSessionRecord:
        record = self.get(session_id)
        now = self._now_fn()
        if self._touch_dialogue is not None:
            self._touch_dialogue(session_id)
        record.last_activity_at = now
        return record
