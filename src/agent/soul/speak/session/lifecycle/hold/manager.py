from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ...chunk import SpeakTurnChunk
from ..init.bootstrap import SessionBootstrap
from ..types import SessionEndReason, SessionEndResult, SessionOpenTrigger, TurnRecordResult
from .semantic import SemanticSessionBoundary

if TYPE_CHECKING:
    from ....io.inbound.ingest import SpeakIngestResult
else:
    SpeakIngestResult = object  # noqa: N806


class SessionHolder:
    """会话持有与销毁：finalize → life 打包、turn 记账、语义轮转。"""

    def __init__(
        self,
        bootstrap: SessionBootstrap,
        *,
        semantic: SemanticSessionBoundary | None = None,
        on_rotate: Callable[[str], None] | None = None,
    ) -> None:
        self._bootstrap = bootstrap
        self._semantic = semantic
        self._on_rotate = on_rotate or (lambda _sid: None)
        self._record_fn: Callable[[SpeakTurnChunk], SpeakIngestResult] | None = None
        bootstrap.registry._on_temporal_expire = self.finalize_session_temporal

    @property
    def registry(self):
        return self._bootstrap.registry

    def bind_record_fn(self, record_fn: Callable[[SpeakTurnChunk], SpeakIngestResult]) -> None:
        self._record_fn = record_fn

    def _close_payload(self, session_id: str) -> dict:
        lifecycle = self._bootstrap.registry.lifecycle
        if lifecycle is None:
            return {"ok": True, "session_id": session_id, "ingested": False}
        return lifecycle.close_dialogue_interaction(session_id)

    def _start_payload(
        self,
        session_id: str,
        *,
        trigger: SessionOpenTrigger = "user_message",
    ) -> dict:
        lifecycle = self._bootstrap.registry.lifecycle
        if lifecycle is None:
            return {"ok": True, "session_id": session_id}
        return lifecycle.start_dialogue_session(session_id, trigger=trigger)

    def _notify_rotate(self, session_id: str) -> None:
        if self._semantic is not None:
            self._semantic.on_session_rotate(session_id)
        self._on_rotate(session_id)

    def _payload_to_end_result(
        self,
        session_id: str,
        *,
        reason: SessionEndReason,
        generation: int,
        close_payload: dict,
        notes: list[str],
    ) -> SessionEndResult:
        return SessionEndResult(
            session_id=session_id,
            reason=reason,
            generation=generation,
            ingested=bool(close_payload.get("ingested")),
            experience_id=str(close_payload.get("experience_id", "")),
            turn_index=int(close_payload.get("turn_index", 0) or 0),
            source=str(close_payload.get("source", "")),
            notes=notes,
        )

    def finalize_session(
        self,
        session_id: str,
        *,
        reason: SessionEndReason,
        note: str = "",
        start_trigger: SessionOpenTrigger = "user_message",
    ) -> SessionEndResult:
        notes: list[str] = []
        if note:
            notes.append(note)

        close_payload = self._close_payload(session_id)
        if close_payload.get("ingested"):
            notes.append("life: dialogue closed and ingested")
        else:
            notes.append("life: dialogue closed (empty)")

        self._start_payload(session_id, trigger=start_trigger)

        record = self._bootstrap.registry.rotate_generation(session_id)
        self._bootstrap.started_generations[session_id] = record.generation
        self._notify_rotate(session_id)

        return self._payload_to_end_result(
            session_id,
            reason=reason,
            generation=record.generation,
            close_payload=close_payload,
            notes=notes,
        )

    def finalize_session_temporal(self, session_id: str) -> SessionEndResult:
        return self.finalize_session(
            session_id,
            reason="temporal_idle",
            note=f"temporal rotate: idle>{self._bootstrap.registry.idle_sec:.0f}s",
        )

    def terminate(
        self,
        session_id: str,
        *,
        reason: SessionEndReason,
        note: str = "",
    ) -> SessionEndResult:
        return self.finalize_session(session_id, reason=reason, note=note)

    def record_turn(
        self,
        chunk: SpeakTurnChunk,
        *,
        on_after: Callable[[str], None] | None = None,
    ) -> TurnRecordResult:
        if self._record_fn is None:
            raise RuntimeError("SessionHolder.record_fn 未绑定")

        session_id = chunk.session_id
        notes: list[str] = []
        ended: SessionEndResult | None = None

        if self._semantic is not None and self._semantic.should_rotate(session_id, last_turn=chunk):
            reason_text = self._semantic.reason()
            ended = self.finalize_session(
                session_id,
                reason="semantic_shift",
                note=f"semantic rotate: {reason_text}",
            )
            notes.extend(ended.notes)

        ingest = self._record_fn(chunk)
        self._bootstrap.registry.touch(session_id)
        if on_after is not None:
            on_after(session_id)

        return TurnRecordResult(
            recorded=True,
            exchange_id=ingest.exchange.id,
            notes=notes,
            ended=ended,
        )
