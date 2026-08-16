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
    """将角色台词收束成一次完整交付，节奏由后端 render_time 控制。"""
    answer = timeline.answer_text.strip()
    segments = (
        [
            ReplySegment(
                text=answer,
                wait_ms=0,
                wait_reason="character_speak",
                continuity="finish",
            )
        ]
        if answer
        else []
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
    """Role 时间线 → 按 ops 索引顺序出站；speak / body 交替保留 order。"""
    ops: list[OutboundOp] = []
    fallback_order = 0

    def _order_of(top) -> int:
        nonlocal fallback_order
        raw = top.meta.get("order") if isinstance(top.meta, dict) else None
        if raw is not None:
            order = int(raw)
            fallback_order = max(fallback_order, order + 1)
            return order
        order = fallback_order
        fallback_order += 1
        return order

    for top in timeline.ops:
        if top.kind == "think":
            thought = top.body.strip()
            if thought:
                order = _order_of(top)
                ops.append(
                    OutboundOp(
                        kind="think",
                        text=thought,
                        meta={"role_op": "think", "field": "thought", "order": order},
                    )
                )
            continue
        if top.kind == "body":
            body = top.body.strip()
            if body:
                order = _order_of(top)
                ops.append(
                    OutboundOp(
                        kind="action",
                        text=body,
                        meta={"role_op": "body", "field": "body", "order": order},
                    )
                )
            continue
        if top.kind == "emit":
            pieces = [str(t or "").strip() for t in top.texts if str(t or "").strip()]
            base = None
            if isinstance(top.meta, dict) and top.meta.get("order") is not None:
                base = int(top.meta["order"])
            for offset, piece in enumerate(pieces):
                if base is not None:
                    order = base + offset
                    fallback_order = max(fallback_order, order + 1)
                else:
                    order = fallback_order
                    fallback_order += 1
                ops.append(
                    OutboundOp(
                        kind="speak",
                        text=piece,
                        meta={"role_op": "speak", "field": "speak", "order": order},
                    )
                )
            continue
        if top.kind == "wait":
            order = _order_of(top)
            ops.append(
                OutboundOp(
                    kind="wait",
                    seconds=float(top.seconds or 0.0),
                    meta={"role_op": "wait", "field": "wait", "order": order},
                )
            )
            continue
        if top.kind == "silence":
            continue
    if finish:
        ops.append(
            OutboundOp(
                kind="finish",
                text="",
                final=True,
                meta={"role_timeline": True, "field": "finish", "order": fallback_order},
            )
        )
    # 稳定按索引排序，避免 LLM 乱序输出时前端错乱
    visible = [op for op in ops if op.kind != "finish"]
    visible.sort(key=lambda op: int(op.meta.get("order", 0) or 0))
    finish_ops = [op for op in ops if op.kind == "finish"]
    return OutboundRequest(
        session_id=session_id.strip(),
        ops=tuple(visible + finish_ops),
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
