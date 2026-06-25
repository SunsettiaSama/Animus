from __future__ import annotations

from ..state.core.types import SessionSnapshot
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object
from .fallback import fallback_director_output, fallback_user_intent


class UserIntentDirector:
    name = "user_intent"

    _SYSTEM = (
        "你是用户意图导演。根据用户输入猜测意图标签与置信度(0~1)。\n"
        '只输出 JSON：{"intent":"question|statement|ack|vent|share|idle",'
        '"confidence":0.0,"notes":"…"}'
    )

    def __init__(self, llm: DirectorLLMCaller) -> None:
        self._llm = llm

    def run(self, snapshot: SessionSnapshot, *, user_text: str = "") -> DirectorOutput:
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        if not text:
            intent, confidence = fallback_user_intent("")
            return DirectorOutput(
                director=self.name,
                payload={"intent": intent, "confidence": confidence},
                reason="empty_user_text",
            )
        prompt = (
            f"user_text={text[:400]}\n"
            f"context={snapshot.dialogue.context_distill.strip()[:300]}"
        )
        raw = self._llm.generate_json(
            system=self._SYSTEM,
            user=prompt,
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        payload = extract_json_object(raw)
        if not payload:
            return fallback_director_output(
                self.name,
                snapshot,
                user_text=text,
                raw=raw,
            )
        intent = str(payload.get("intent", "statement")).strip() or "statement"
        confidence = float(payload.get("confidence", 0.5) or 0.5)
        confidence = max(0.0, min(1.0, confidence))
        return DirectorOutput(
            director=self.name,
            payload={
                "intent": intent,
                "confidence": confidence,
                "notes": str(payload.get("notes", "")).strip(),
            },
            reason="intent_ok",
        )


def apply_user_intent_output(state, output: DirectorOutput) -> None:
    state.user_intent = str(output.payload.get("intent", "")).strip()
    state.user_intent_confidence = float(output.payload.get("confidence", 0.0) or 0.0)
