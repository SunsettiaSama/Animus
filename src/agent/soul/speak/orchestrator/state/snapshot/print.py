from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.delivery import DeliveryPlan
    from ..core.types import SessionSnapshot
    from ..runtime.store import StateStore


def format_delivery_sample(plan: DeliveryPlan, *, user_text: str = "") -> str:
    lines: list[str] = []
    if user_text.strip():
        lines.append(f"user: {user_text.strip()}")
    for segment in plan.segments:
        if segment.wait_ms <= 0:
            lines.append(f"agent: {segment.text}[立刻回复]")
        else:
            reason = segment.wait_reason.strip() or "停顿"
            lines.append(
                f"agent: {segment.text}[等待{segment.wait_ms}ms回复] # {reason}",
            )
    return "\n".join(lines)


def print_session_snapshot(
    snapshot: SessionSnapshot,
    *,
    state_store: StateStore | None = None,
) -> str:
    lines: list[str] = [
        f"snapshot_id={snapshot.snapshot_id}",
        f"schema_version={snapshot.schema_version}",
        f"session_id={snapshot.session_id}",
        f"turn_index={snapshot.signals.turn_index}",
        f"generation={snapshot.signals.generation}",
        f"push_phase={snapshot.runtime.push_phase}",
        f"segment={snapshot.runtime.current_segment_index}/{snapshot.runtime.segment_total}",
    ]
    if snapshot.dialogue.user_text.strip():
        lines.append(f"user_text={snapshot.dialogue.user_text.strip()[:200]}")
    if state_store is not None:
        state = state_store.session(snapshot.session_id)
        lines.append(f"rhythm={state.rhythm.phase}")
        if state.outline.current_step is not None:
            step = state.outline.current_step
            lines.append(f"outline_step={step.label}")
        lines.append(f"user_intent={state.user_intent}({state.user_intent_confidence:.2f})")
        lines.append(f"speak_gate={state.speak_gate}")
        plan = state.delivery_plan or state.pending_delivery_plan
        if plan is not None and not plan.is_empty:
            lines.append("delivery_sample:")
            lines.append(
                format_delivery_sample(
                    plan,
                    user_text=snapshot.dialogue.user_text,
                ),
            )
    return "\n".join(lines)


def session_snapshot_debug(
    snapshot: SessionSnapshot,
    *,
    state_store: StateStore | None = None,
) -> dict[str, Any]:
    out = snapshot.snapshot()
    out["print"] = print_session_snapshot(snapshot, state_store=state_store)
    return out
