from __future__ import annotations

import re
from typing import Any

from ..state.core.delivery import DeliveryPlan, ReplySegment, build_delivery_plan
from ..state.core.enums import normalize_continuity
from ..state.core.types import SessionSnapshot
from .base import DirectorOutput, extract_json_object, parse_delivery_plan_payload


def fallback_delivery_plan(
    snapshot: SessionSnapshot,
    *,
    user_text: str = "",
    raw: str = "",
) -> DeliveryPlan:
    payload = extract_json_object(raw)
    if payload:
        return parse_delivery_plan_payload(
            payload,
            turn_index=snapshot.signals.turn_index,
            plan_id=snapshot.snapshot_id,
        )
    text = user_text.strip() or snapshot.dialogue.user_text.strip()
    if not text:
        return build_delivery_plan(segments=[], continuity="finish")
    reply = _regex_reply_line(raw)
    if not reply:
        reply = "嗯，我在听。"
    segment = ReplySegment(
        text=reply[:120],
        wait_ms=120,
        wait_reason="兜底首段",
        continuity="finish",
    )
    return build_delivery_plan(
        segments=[segment],
        continuity="finish",
        sample_narration=f"user: {text}\nagent: {reply}[立刻回复]",
        plan_id=snapshot.snapshot_id,
        turn_index=snapshot.signals.turn_index,
    )


def _regex_reply_line(raw: str) -> str:
    if not raw.strip():
        return ""
    patterns = (
        r'"text"\s*:\s*"([^"]+)"',
        r"agent:\s*(.+)",
        r"回复[:：]\s*(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return match.group(1).strip()
    line = raw.strip().splitlines()[0].strip()
    return line[:120]


def fallback_outline_phase(snapshot: SessionSnapshot) -> str:
    if snapshot.signals.turn_index <= 1:
        return "opening"
    if snapshot.runtime.push_phase == "pushing":
        return "exchange"
    return "exchange"


def fallback_user_intent(user_text: str) -> tuple[str, float]:
    text = user_text.strip()
    if not text:
        return "idle", 0.0
    if text.endswith("?"):
        return "question", 0.55
    if len(text) <= 6:
        return "ack", 0.45
    return "statement", 0.5


def fallback_speak_gate(snapshot: SessionSnapshot, *, has_plan: bool) -> str:
    if snapshot.runtime.push_phase == "pushing":
        return "hold"
    if has_plan:
        return "speak"
    if snapshot.runtime.typing_active and not snapshot.runtime.typing_idle:
        return "listen"
    return "hold"


def fallback_director_output(
    director: str,
    snapshot: SessionSnapshot,
    *,
    user_text: str = "",
    raw: str = "",
) -> DirectorOutput:
    if director == "turn_delivery":
        plan = fallback_delivery_plan(snapshot, user_text=user_text, raw=raw)
        return DirectorOutput(
            director=director,
            payload={"delivery_plan": plan.snapshot()},
            reason="fallback_delivery",
            used_fallback=True,
        )
    if director == "outline":
        phase = fallback_outline_phase(snapshot)
        return DirectorOutput(
            director=director,
            payload={"rhythm_phase": phase, "step_label": "respond"},
            reason="fallback_outline",
            used_fallback=True,
        )
    if director == "user_intent":
        intent, confidence = fallback_user_intent(user_text)
        return DirectorOutput(
            director=director,
            payload={"intent": intent, "confidence": confidence},
            reason="fallback_intent",
            used_fallback=True,
        )
    if director == "speak_gate":
        gate = fallback_speak_gate(snapshot, has_plan=False)
        return DirectorOutput(
            director=director,
            payload={"action": gate},
            reason="fallback_gate",
            used_fallback=True,
        )
    return DirectorOutput(
        director=director,
        payload={},
        reason="fallback_empty",
        used_fallback=True,
    )


def parse_module_inject_payload(payload: dict[str, Any]) -> dict[str, bool]:
    modules = payload.get("modules") or payload.get("refresh") or {}
    if not isinstance(modules, dict):
        return {}
    out: dict[str, bool] = {}
    for key, value in modules.items():
        out[str(key)] = bool(value)
    return out
