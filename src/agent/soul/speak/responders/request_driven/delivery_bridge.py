from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agent.soul.speak.io.outbound.protocol import OutboundOp, OutboundRequest
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    DeliveryPlan,
    ReplySegment,
    build_delivery_plan,
)

from .timeline import RoleTimeline


@dataclass
class RoleTurnResult:
    answer: str
    delivery_plan: DeliveryPlan
    outbound: OutboundRequest | None = None
    body_actions: tuple[str, ...] = ()
    thoughts: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()
    events: list[SpeakStreamEvent] = field(default_factory=list)


def timeline_to_delivery_plan(
    timeline: RoleTimeline,
    *,
    turn_index: int,
    plan_id: str,
) -> DeliveryPlan:
    """将 Role 时间线折叠为 DeliveryPlan（以 Role 为准，覆盖导演 pacing）。"""
    segments: list[ReplySegment] = []
    pending_wait_ms = 0
    pending_reason = ""
    for op in timeline.ops:
        if op.kind == "think":
            continue
        if op.kind == "wait":
            pending_wait_ms += op.wait_ms
            pending_reason = "role_wait"
            continue
        if op.kind == "silence":
            pending_wait_ms += op.wait_ms
            pending_reason = "role_silence"
            continue
        if op.kind == "body":
            continue
        if op.kind == "emit":
            texts = [t for t in op.texts if t.strip()]
            if not texts:
                pending_wait_ms = 0
                pending_reason = ""
                continue
            for index, text in enumerate(texts):
                wait_ms = pending_wait_ms if index == 0 else 0
                reason = pending_reason if index == 0 else "role_emit"
                segments.append(
                    ReplySegment(
                        text=text,
                        wait_ms=wait_ms,
                        wait_reason=reason or "role_emit",
                        continuity="append" if index < len(texts) - 1 else "finish",
                    )
                )
                pending_wait_ms = 0
                pending_reason = ""
    if not segments and pending_wait_ms > 0:
        segments.append(
            ReplySegment(
                text="",
                wait_ms=pending_wait_ms,
                wait_reason=pending_reason or "role_wait",
                continuity="finish",
            )
        )
    return build_delivery_plan(
        turn_index=turn_index,
        plan_id=plan_id,
        segments=segments,
        continuity="finish",
    )


def timeline_to_outbound_request(
    timeline: RoleTimeline,
    *,
    session_id: str,
    user_text: str = "",
    finish: bool = True,
) -> OutboundRequest:
    """Role 时间线 → 统一 OutboundRequest（可见出站唯一输入形态）。"""
    ops: list[OutboundOp] = []
    for op in timeline.ops:
        if op.kind == "think":
            text = op.body.strip()
            if text:
                ops.append(
                    OutboundOp(
                        kind="think",
                        text=text,
                        meta={"role_op": "think", "field": "thought"},
                    )
                )
            continue
        if op.kind in ("wait", "silence"):
            ops.append(
                OutboundOp(
                    kind=op.kind,
                    seconds=max(0.0, float(op.seconds)),
                    meta={
                        "role_op": op.kind,
                        "silence": op.kind == "silence",
                        "field": op.kind,
                    },
                )
            )
            continue
        if op.kind == "body":
            text = op.body.strip()
            if text:
                ops.append(
                    OutboundOp(
                        kind="action",
                        text=text,
                        meta={"role_op": "body", "field": "body"},
                    )
                )
            continue
        if op.kind == "emit":
            for text in op.texts:
                if text.strip():
                    ops.append(
                        OutboundOp(
                            kind="speak",
                            text=text.strip(),
                            meta={"role_op": "emit", "field": "speak"},
                        )
                    )
    if finish:
        ops.append(
            OutboundOp(
                kind="finish",
                text="",
                final=True,
                meta={"role_timeline": True, "field": "finish"},
            )
        )
    return OutboundRequest(
        session_id=session_id.strip(),
        ops=tuple(ops),
        user_text=user_text,
        meta={"source": "role_timeline"},
    )


def execute_timeline_sync(
    timeline: RoleTimeline,
    *,
    emit_fn: Callable[[SpeakStreamEvent], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> RoleTurnResult:
    """兼容测试：把时间线转为 OutboundRequest 后本地回放事件（不经 session）。"""
    from agent.soul.speak.io.outbound.execute import execute_outbound

    request = timeline_to_outbound_request(timeline, session_id="role-timeline", finish=False)
    events: list[SpeakStreamEvent] = []

    def _emit(sid: str, event: SpeakStreamEvent) -> None:
        events.append(event)
        if emit_fn is not None:
            emit_fn(event)

    def _sleep(seconds: float) -> None:
        if sleep_fn is not None:
            sleep_fn(seconds)

    result = execute_outbound(request, emit_fn=_emit, sleep_fn=_sleep)
    plan = timeline_to_delivery_plan(timeline, turn_index=0, plan_id="role-timeline")
    bodies = tuple(op.body.strip() for op in timeline.ops if op.kind == "body" and op.body.strip())
    thoughts = tuple(op.body.strip() for op in timeline.ops if op.kind == "think" and op.body.strip())
    return RoleTurnResult(
        answer=result.answer or timeline.answer_text,
        delivery_plan=plan,
        outbound=request,
        body_actions=bodies,
        thoughts=thoughts,
        ignored=timeline.ignored,
        events=events or result.events,
    )
