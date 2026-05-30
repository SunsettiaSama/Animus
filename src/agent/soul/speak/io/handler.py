from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from agent.soul.handlers.api._llm import resolve_module_llm
from agent.soul.ports import SpeakExperiencePort
from infra.llm import BaseLLM

from .actions import SpeakAction
from ..session import SpeakFeelingChunk, SpeakSubjectiveChunk
from ..service import SpeakService

if TYPE_CHECKING:
    from agent.soul.ports import LLMServicePort


class SpeakHandler:
    """Speak API Handler：会话记账 + experience 穿透 + LLM 生成。"""

    DEFAULT_AUX_NAME = "speak"

    def __init__(
        self,
        *,
        get_speak_service: Callable[[], SpeakService],
        experience: SpeakExperiencePort,
        llm_service: LLMServicePort | None = None,
        llm_aux_name: str = DEFAULT_AUX_NAME,
        primary_llm: BaseLLM | None = None,
    ) -> None:
        self._get_speak_service = get_speak_service
        self._experience = experience
        self._llm_service = llm_service
        self._llm_aux_name = llm_aux_name
        self._primary_llm = primary_llm

    def resolve_llm(self) -> BaseLLM | None:
        return resolve_module_llm(
            self._llm_service,
            self._llm_aux_name,
            self._primary_llm,
        )

    @property
    def api(self) -> SpeakService:
        service = self._get_speak_service()
        llm = self.resolve_llm()
        if llm is not None and service.llm_engine.llm is None:
            service.llm_engine.set_llm(llm)
        return service

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

        if action == SpeakAction.GENERATE:
            return self._generate(payload)

        if action == SpeakAction.GENERATE_STREAM:
            return self._generate_stream(payload)

        if action == SpeakAction.RUN_TURN:
            return self._run_turn(payload)

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
            text = self._experience.dialogue.working_memory_text(
                payload["session_id"],
            )
            return {"session_id": payload["session_id"], "text": text}

        if action == SpeakAction.DIALOGUE_STATE:
            return self._dialogue_state(payload)

        raise ValueError(f"unknown speak action: {action!r}")

    def _open_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        trigger = str(payload.get("trigger", "user_message"))
        open_result = self.api.session_manager.open(session_id, trigger=trigger)
        state = self._experience.dialogue.state(session_id)
        return {
            "ok": True,
            "session_id": session_id,
            "trigger": trigger,
            "generation": open_result.generation,
            "turn_count": len(state.session.turns) if state is not None else 0,
            "notes": list(open_result.notes),
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
        unit = self._experience.close_dialogue(session_id)
        if unit is None:
            return {"ok": True, "session_id": session_id, "ingested": False}
        return {
            "ok": True,
            "session_id": session_id,
            "ingested": True,
            "source": unit.source,
            "turn_index": unit.situation.turn_index,
            "experience_id": unit.id,
        }

    def _open_outbound(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        message = str(payload.get("message", ""))
        proactive_intent_id = str(payload.get("proactive_intent_id", ""))
        open_result = self.api.session_manager.open(
            session_id,
            trigger="proactive_outbound",
            proactive_message=message,
            proactive_intent_id=proactive_intent_id,
        )
        return {
            "ok": True,
            "session_id": session_id,
            "message": message,
            "proactive_intent_id": proactive_intent_id,
            "generation": open_result.generation,
            "proactive_opened": open_result.proactive_opened,
            "notes": list(open_result.notes),
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

    def _generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id", "tao")
        text = str(payload.get("text", ""))
        system = str(payload.get("system", ""))
        context = str(payload.get("context", ""))
        result = self.api.generate(session_id, text, system=system, context=context)
        return {
            "ok": True,
            "session_id": session_id,
            "text": result.text,
        }

    def _generate_stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id", "tao")
        text = str(payload.get("text", ""))
        system = str(payload.get("system", ""))
        context = str(payload.get("context", ""))
        result = self.api.generate_stream(session_id, text, system=system, context=context)
        return {
            "ok": True,
            "session_id": session_id,
            "text": result.text,
            "chunks": list(result.chunks),
        }

    def _run_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id", "tao")
        text = str(payload.get("text", payload.get("user_text", "")))
        stream = bool(payload.get("stream", False))
        mode = str(payload.get("mode", "inbound"))
        result = self.api.run_turn(
            session_id,
            text,
            stream=stream,
            mode="proactive" if mode == "proactive" else "inbound",
        )
        return {
            "ok": True,
            "session_id": result.session_id,
            "answer": result.answer,
            "output": result.output.to_dict() if result.output else {},
            "session_state": result.meta.get("session_state", "finish"),
            "queued": bool(result.meta.get("queued", False)),
            "interrupt": bool(result.meta.get("interrupt", False)),
            "queue_decision_maintain": result.meta.get("queue_decision_maintain"),
            "recorded": result.recorded,
            "bundle": result.bundle.summary_for_log(),
            "events": [
                {
                    "kind": event.kind,
                    "text": event.text,
                    "final": event.final,
                    "meta": dict(event.meta),
                }
                for event in result.stream_events
            ],
            "notes": list(result.notes),
        }

    def _dialogue_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload["session_id"]
        state = self._experience.dialogue.state(session_id)
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
