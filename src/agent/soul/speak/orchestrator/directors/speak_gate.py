from __future__ import annotations

from ..state.core.types import SessionSnapshot
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object
from .fallback import fallback_director_output, fallback_speak_gate


class SpeakGateDirector:
    name = "speak_gate"

    _SYSTEM = (
        "你是开口门控导演。结合大纲与交付计划决定 listen/speak/hold/brew。\n"
        '只输出 JSON：{"action":"listen|speak|hold|brew","reason":"…"}'
    )

    def __init__(self, llm: DirectorLLMCaller) -> None:
        self._llm = llm

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str = "",
        has_delivery_plan: bool = False,
    ) -> DirectorOutput:
        prompt = self._build_prompt(
            snapshot,
            user_text=user_text,
            has_delivery_plan=has_delivery_plan,
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
            gate = fallback_speak_gate(snapshot, has_plan=has_delivery_plan)
            return DirectorOutput(
                director=self.name,
                payload={"action": gate},
                reason="fallback_gate",
                used_fallback=True,
            )
        action = str(payload.get("action", "hold")).strip().lower()
        if action not in ("listen", "speak", "hold", "brew"):
            action = fallback_speak_gate(snapshot, has_plan=has_delivery_plan)
        return DirectorOutput(
            director=self.name,
            payload={
                "action": action,
                "reason": str(payload.get("reason", "")).strip(),
            },
            reason="gate_ok",
        )

    def _build_prompt(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str,
        has_delivery_plan: bool,
    ) -> str:
        lines = [
            f"typing_active={snapshot.runtime.typing_active}",
            f"typing_idle={snapshot.runtime.typing_idle}",
            f"push_phase={snapshot.runtime.push_phase}",
            f"has_delivery_plan={has_delivery_plan}",
            f"brew_queue_depth={snapshot.runtime.brew_queue_depth}",
        ]
        if user_text.strip():
            lines.append(f"user_text={user_text.strip()[:200]}")
        return "\n".join(lines)


def apply_speak_gate_output(state, output: DirectorOutput) -> None:
    state.speak_gate = str(output.payload.get("action", "hold")).strip() or "hold"
