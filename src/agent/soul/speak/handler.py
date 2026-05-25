from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from .actions import SpeakAction
from .chunk import SpeakFeelingChunk, SpeakSubjectiveChunk
from .service import SpeakService

if TYPE_CHECKING:
    from agent.soul.service import SoulService

__all__ = ["SpeakAction", "SpeakHandler"]


class SpeakHandler:
    """Speak API Handler：会话记账 + presence/experience 穿透。"""

    def __init__(self, soul: SoulService) -> None:
        self._soul = soul

    @property
    def api(self) -> SpeakService:
        return self._soul._ensure_speak_service()

    def handle(self, action: str, payload: dict[str, Any]) -> Any:
        if action == SpeakAction.OPEN_SESSION:
            return self._open_session(payload)

        if action == SpeakAction.RECORD_DIALOGUE:
            return self._record_dialogue(payload)

        if action == SpeakAction.CLOSE_SESSION:
            return self._close_session(payload)

        if action == SpeakAction.OPEN_OUTBOUND:
            return self._open_outbound(payload)

        if action == SpeakAction.INGEST_QUESTION:
            return self._ingest_question(payload)

        if action == SpeakAction.DELIVER:
            return self._deliver(payload)

        if action == SpeakAction.DRIVE_SNAPSHOT:
            snap = self.api.drive_snapshot(payload["session_id"])
            return asdict(snap)

        if action == SpeakAction.EVALUATE_DRIVE:
            result = self.api.evaluate_drive(payload["session_id"])
            return {
                "snapshot": asdict(result.snapshot),
                "should_speak": result.should_speak,
                "speak_reason": result.speak_reason,
                "notes": list(result.notes),
            }

        if action == SpeakAction.WORKING_MEMORY:
            text = self._soul.experience.dialogue.working_memory_text(
                payload["session_id"],
            )
            return {"session_id": payload["session_id"], "text": text}

        if action == SpeakAction.DIALOGUE_STATE:
            return self._dialogue_state(payload)

        raise ValueError(f"unknown speak action: {action!r}")

    def _open_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        state = self._soul.experience.dialogue.open_session(session_id)
        return {
            "ok": True,
            "session_id": state.session_id,
            "turn_count": len(state.session.turns),
        }

    def _record_dialogue(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id", "tao")
        user_text = payload.get("user_text") or payload.get("question", "")
        agent_text = payload.get("agent_text") or payload.get("answer", "")

        result = self.api.record_dialogue(
            session_id=session_id,
            user_text=user_text,
            agent_text=agent_text,
            subjective=SpeakSubjectiveChunk(
                perception=str(payload.get("perception", "")),
                narration=str(payload.get("narration", "")),
                prior_thought=str(payload.get("prior_thought", "")),
            ),
            feeling=SpeakFeelingChunk(
                emotion=str(payload.get("emotion", "")),
                salience=str(payload.get("salience_note", payload.get("salience", ""))),
                valence=str(payload.get("valence_note", payload.get("valence", ""))),
                arousal=str(payload.get("arousal_note", payload.get("arousal", ""))),
            ),
            activated_memory_ids=payload.get("activated_memory_ids"),
            proactive_intent_id=str(payload.get("proactive_intent_id", "")),
        )
        exchange = result.exchange
        subj = exchange.subjective
        return {
            "ok": True,
            "session_id": exchange.session_id,
            "exchange_id": exchange.id,
            "subjective": {
                "perception": subj.perception,
                "narration": subj.narration,
                "prior_thought": subj.prior_thought,
            },
            "feeling": {
                "emotion": exchange.feeling.emotion,
                "salience": exchange.feeling.salience,
                "valence": exchange.feeling.valence,
                "arousal": exchange.feeling.arousal,
            },
            "notes": list(result.notes),
        }

    def _close_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id", "tao")
        unit = self._soul.experience.dialogue.close_dialogue(
            self._soul.presence,
            session_id,
        )
        if unit is None:
            return {"ok": True, "session_id": session_id, "ingested": False}
        return {
            "ok": True,
            "session_id": session_id,
            "ingested": True,
            "source": unit.source,
            "turn_index": unit.situation.turn_index,
        }

    def _open_outbound(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        message = str(payload.get("message", ""))
        proactive_intent_id = str(payload.get("proactive_intent_id", ""))
        self._soul.experience.dialogue.open_outbound(
            session_id,
            message,
            proactive_intent_id=proactive_intent_id,
        )
        return {
            "ok": True,
            "session_id": session_id,
            "message": message,
            "proactive_intent_id": proactive_intent_id,
        }

    def _ingest_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        text = str(payload.get("text", ""))
        result = self.api.ingest_question(session_id, text)
        exchange = result.exchange
        return {
            "ok": True,
            "session_id": exchange.session_id,
            "exchange_id": exchange.id,
            "question": exchange.question.text,
            "notes": list(result.notes),
        }

    def _deliver(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        text = str(payload.get("text", ""))
        final = bool(payload.get("final", True))
        result = self.api.speak(session_id, text, final=final)
        answer = result.answer
        return {
            "ok": True,
            "session_id": session_id,
            "text": answer.text,
            "final": answer.final,
            "notes": list(result.notes),
        }

    def _dialogue_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        state = self._soul.experience.dialogue.state(session_id)
        if state is None:
            return {
                "session_id": session_id,
                "open": False,
                "turn_count": 0,
                "working_memory": "",
            }
        return {
            "session_id": session_id,
            "open": True,
            "turn_count": len(state.session.turns),
            "working_memory": state.working_memory_text(),
            "direction": state.session.direction.value,
            "proactive_intent_id": state.session.proactive_intent_id,
        }
