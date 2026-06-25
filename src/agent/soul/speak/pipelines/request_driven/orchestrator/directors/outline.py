from __future__ import annotations

from ..state.core.outline import OutlineStep
from ..state.core.types import SessionSnapshot
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object
from .fallback import fallback_director_output, fallback_outline_phase


class OutlineDirector:
    name = "outline"

    _SYSTEM = (
        "你是对话节奏导演。根据快照规划当前大纲步骤与节奏阶段。\n"
        '只输出 JSON：{"rhythm_phase":"opening|exchange|deepening|closing|idle",'
        '"step_label":"…","step_goal":"…","notes":["…"]}'
    )

    def __init__(self, llm: DirectorLLMCaller) -> None:
        self._llm = llm

    def run(self, snapshot: SessionSnapshot, *, user_text: str = "") -> DirectorOutput:
        prompt = self._build_prompt(snapshot, user_text=user_text)
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
                user_text=user_text,
                raw=raw,
            )
        phase = str(payload.get("rhythm_phase", "")).strip() or fallback_outline_phase(snapshot)
        return DirectorOutput(
            director=self.name,
            payload={
                "rhythm_phase": phase,
                "step_label": str(payload.get("step_label", "respond")).strip(),
                "step_goal": str(payload.get("step_goal", "")).strip(),
                "notes": payload.get("notes") or [],
            },
            reason="outline_ok",
        )

    def _build_prompt(self, snapshot: SessionSnapshot, *, user_text: str) -> str:
        lines = [
            f"turn_index={snapshot.signals.turn_index}",
            f"push_phase={snapshot.runtime.push_phase}",
            f"segment={snapshot.runtime.current_segment_index}/{snapshot.runtime.segment_total}",
            f"partial={snapshot.runtime.partial_output_preview[:200]}",
        ]
        if user_text.strip():
            lines.append(f"user_text={user_text.strip()[:400]}")
        if snapshot.dialogue.context_distill.strip():
            lines.append(f"context={snapshot.dialogue.context_distill.strip()[:500]}")
        return "\n".join(lines)


def apply_outline_output(state, output: DirectorOutput) -> None:
    phase = str(output.payload.get("rhythm_phase", "exchange"))
    state.rhythm.set_phase(phase)
    label = str(output.payload.get("step_label", "respond")).strip() or "respond"
    goal = str(output.payload.get("step_goal", "")).strip()
    if not state.outline.steps:
        state.outline.steps.append(OutlineStep(label=label, goal=goal))
    else:
        idx = state.outline.current_step_index
        if 0 <= idx < len(state.outline.steps):
            state.outline.steps[idx].label = label
            state.outline.steps[idx].goal = goal
        else:
            state.outline.steps.append(OutlineStep(label=label, goal=goal))
    notes = output.payload.get("notes") or []
    if isinstance(notes, list):
        state.outline.notes.extend(str(item) for item in notes if str(item).strip())
