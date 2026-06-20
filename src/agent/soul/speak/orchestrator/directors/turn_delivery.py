from __future__ import annotations

from ..state.core.delivery import build_delivery_plan
from ..state.core.types import SessionSnapshot
from .base import (
    DirectorLLMCaller,
    DirectorOutput,
    extract_json_object,
    parse_delivery_plan_payload,
)
from .fallback import fallback_director_output


class TurnDeliveryDirector:
    name = "turn_delivery"

    _SYSTEM = (
        "你是对话交付导演。根据上下文决定分段回复、每段等待时间与原因。\n"
        "wait_ms: 首段>=120，普通200~2800，重情绪<=4200；0表示立刻。\n"
        '只输出 JSON：{"continuity":"append|finish","sample_narration":"…",'
        '"segments":[{"text":"…","wait_ms":0,"wait_reason":"…","continuity":"finish"}]}'
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
            output = fallback_director_output(
                self.name,
                snapshot,
                user_text=user_text,
                raw=raw,
            )
            return output
        plan = parse_delivery_plan_payload(
            payload,
            turn_index=snapshot.signals.turn_index,
            plan_id=snapshot.snapshot_id,
        )
        return DirectorOutput(
            director=self.name,
            payload={"delivery_plan": plan.snapshot()},
            reason="delivery_ok",
        )

    def should_continue_on_disconnect(self, snapshot: SessionSnapshot) -> bool:
        if snapshot.runtime.push_phase != "pushing":
            return False
        if snapshot.runtime.current_segment_index >= snapshot.runtime.segment_total:
            return False
        prompt = (
            f"push_phase={snapshot.runtime.push_phase}\n"
            f"segment={snapshot.runtime.current_segment_index}/{snapshot.runtime.segment_total}\n"
            f"partial={snapshot.runtime.partial_output_preview[:200]}\n"
            "是否继续推送未完成分段？输出 JSON：{\"continue\":true|false,\"reason\":\"…\"}"
        )
        raw = self._llm.generate_json(
            system="你是断连恢复导演，只输出 continue 布尔决策 JSON。",
            user=prompt,
            session_id=snapshot.session_id,
            director=f"{self.name}.disconnect",
            turn_index=snapshot.signals.turn_index,
        )
        payload = extract_json_object(raw)
        if not payload:
            return snapshot.runtime.current_segment_index < snapshot.runtime.segment_total
        return bool(payload.get("continue", False))

    def _build_prompt(self, snapshot: SessionSnapshot, *, user_text: str) -> str:
        lines = [
            f"turn_index={snapshot.signals.turn_index}",
            f"push_phase={snapshot.runtime.push_phase}",
            f"segment={snapshot.runtime.current_segment_index}/{snapshot.runtime.segment_total}",
            f"partial={snapshot.runtime.partial_output_preview[:300]}",
            f"intent={snapshot.orchestrator.director_decisions.get('user_intent', '')}",
        ]
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        if text:
            lines.append(f"user_text={text[:400]}")
        if snapshot.dialogue.working_memory.strip():
            lines.append(f"working_memory={snapshot.dialogue.working_memory.strip()[:400]}")
        return "\n".join(lines)


def apply_turn_delivery_output(state, output: DirectorOutput, *, pending: bool = True) -> None:
    payload = output.payload.get("delivery_plan") or {}
    if not payload:
        return
    from ..state.core.delivery import ReplySegment
    from ..state.core.enums import normalize_continuity

    segments = []
    for item in payload.get("segments") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            ReplySegment(
                text=text,
                wait_ms=int(item.get("wait_ms", 0) or 0),
                wait_reason=str(item.get("wait_reason", "")).strip(),
                continuity=normalize_continuity(str(item.get("continuity", "finish"))),
            ),
        )
    plan = build_delivery_plan(
        segments=segments,
        continuity=str(payload.get("continuity", "finish")),
        sample_narration=str(payload.get("sample_narration", "")).strip(),
        plan_id=str(payload.get("plan_id", "")).strip(),
        turn_index=int(payload.get("turn_index", 0) or 0),
    )
    if pending:
        state.pending_delivery_plan = plan
    else:
        state.delivery_plan = plan
