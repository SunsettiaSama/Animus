from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from agent.soul.speak.io.outbound.protocol import OutboundOp, OutboundRequest
from agent.soul.speak.io.outbound.render_protocol import SpeakRenderField, render_meta
from agent.soul.speak.io.outbound.render_time import estimate_render_time_ms
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent

if TYPE_CHECKING:
    from agent.soul.speak.io.outbound.stream import SpeakStreamChannel
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
        DeliveryPlan,
    )
    from agent.soul.speak.session import SpeakSessionService

_WAIT_CAP_SEC = 3.0
_TYPING_LEAD_MIN_MS = 80
_TYPING_LEAD_MAX_MS = 120


def _render_hold_seconds(render_time_ms: int) -> float:
    lead = min(_TYPING_LEAD_MAX_MS, max(_TYPING_LEAD_MIN_MS, render_time_ms // 10))
    return max(0.0, (render_time_ms - lead) / 1000.0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OutboundExecuteResult:
    events: list[SpeakStreamEvent] = field(default_factory=list)
    answer: str = ""
    created_at: str = ""


EmitFn = Callable[[str, SpeakStreamEvent], None]
SleepFn = Callable[[float], None]
ShouldContinueFn = Callable[[str], bool]
OnDoneFn = Callable[[str], None]


def execute_outbound(
    request: OutboundRequest,
    *,
    emit_fn: EmitFn,
    session_service: SpeakSessionService | None = None,
    stream_channel: SpeakStreamChannel | None = None,
    sleep_fn: SleepFn | None = None,
    should_continue_fn: ShouldContinueFn | None = None,
    on_done: OnDoneFn | None = None,
) -> OutboundExecuteResult:
    """统一可见出站：begin_push → ops → end_push。"""
    sleep = sleep_fn or time.sleep
    sid = request.session_id.strip()
    if not sid:
        raise ValueError("OutboundRequest.session_id required")
    if not request.ops:
        return OutboundExecuteResult()

    # speak 时刻：出站开始时固化，前端渲染/历史回放一律用此戳
    created_at = str(request.meta.get("created_at") or "").strip() or _now_iso()

    if session_service is not None:
        session_service.queues.begin_push(sid, request.user_text)
    if stream_channel is not None:
        stream_channel.begin_session(sid)

    events: list[SpeakStreamEvent] = []
    spoken: list[str] = []
    has_visible_speak = any(
        op.kind == "speak" and op.text.strip()
        for op in request.ops
    )

    def _emit(event: SpeakStreamEvent) -> None:
        meta = dict(event.meta or {})
        meta.setdefault("created_at", created_at)
        stamped = SpeakStreamEvent(
            kind=event.kind,
            text=event.text,
            final=event.final,
            meta=meta,
        )
        emit_fn(sid, stamped)
        events.append(stamped)

    if request.user_text.strip() and not has_visible_speak:
        render_time_ms = estimate_render_time_ms(request.user_text)
        _emit(
            SpeakStreamEvent(
                kind="agent_typing",
                text="",
                final=False,
                meta=render_meta(
                    "typing",
                    wait_ms=render_time_ms,
                    extra={
                        "render_time_ms": render_time_ms,
                        "render_retracted": True,
                        "wait_reason": "silent_reply",
                    },
                ),
            )
        )
        sleep(render_time_ms / 1000.0)

    for op in request.ops:
        if session_service is not None and session_service.has_user_interrupt(sid):
            break
        if should_continue_fn is not None and not should_continue_fn(sid):
            break
        if op.kind == "think":
            text = op.text.strip()
            if text:
                order_raw = op.meta.get("order")
                order = int(order_raw) if order_raw is not None else None
                _emit(
                    SpeakStreamEvent(
                        kind="thought",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "thought",
                            order=order,
                            extra={**op.meta, "tag": "think"},
                        ),
                    )
                )
            continue
        if op.kind in ("wait", "silence"):
            seconds = min(max(0.0, float(op.seconds)), _WAIT_CAP_SEC)
            wait_ms = int(round(seconds * 1000.0))
            field: SpeakRenderField = "silence" if op.kind == "silence" else "wait"
            order_raw = op.meta.get("order")
            order = int(order_raw) if order_raw is not None else None
            if wait_ms > 0:
                lead = min(_TYPING_LEAD_MAX_MS, max(_TYPING_LEAD_MIN_MS, wait_ms // 10))
                _emit(
                    SpeakStreamEvent(
                        kind="agent_typing",
                        text="",
                        final=False,
                        meta=render_meta(
                            "typing",
                            wait_ms=wait_ms,
                            seconds=seconds,
                            order=order,
                            extra={
                                **op.meta,
                                "wait_reason": op.kind,
                                "silence": op.kind == "silence",
                            },
                        ),
                    )
                )
                sleep(max(0.0, (wait_ms - lead) / 1000.0))
            _emit(
                SpeakStreamEvent(
                    kind="state",
                    text=field,
                    final=False,
                    meta=render_meta(
                        field,
                        wait_ms=wait_ms,
                        seconds=seconds,
                        order=order,
                        extra={
                            **op.meta,
                            "role_op": op.kind,
                            "silence": op.kind == "silence",
                            "tag": "state",
                        },
                    ),
                )
            )
            continue
        if op.kind == "action":
            text = op.text.strip()
            if text:
                render_time_ms = estimate_render_time_ms(text)
                order_raw = op.meta.get("order")
                order = int(order_raw) if order_raw is not None else None
                _emit(
                    SpeakStreamEvent(
                        kind="agent_typing",
                        text="",
                        final=False,
                        meta=render_meta(
                            "typing",
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "render_time_ms": render_time_ms,
                                "render_target": "body",
                                "wait_reason": "render",
                            },
                        ),
                    )
                )
                sleep(_render_hold_seconds(render_time_ms))
                _emit(
                    SpeakStreamEvent(
                        kind="action",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "body",
                            phase=str(op.meta.get("phase") or ""),
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "tag": "action",
                                "render_time_ms": render_time_ms,
                                "render_target": "body",
                            },
                        ),
                    )
                )
            continue
        if op.kind == "observe":
            text = op.text.strip()
            if text:
                render_time_ms = estimate_render_time_ms(text)
                order_raw = op.meta.get("order")
                order = int(order_raw) if order_raw is not None else None
                _emit(
                    SpeakStreamEvent(
                        kind="agent_typing",
                        text="",
                        final=False,
                        meta=render_meta(
                            "typing",
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "render_time_ms": render_time_ms,
                                "render_target": "observe",
                                "wait_reason": "render",
                            },
                        ),
                    )
                )
                sleep(_render_hold_seconds(render_time_ms))
                _emit(
                    SpeakStreamEvent(
                        kind="observe",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "observe",
                            phase=str(op.meta.get("phase") or ""),
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "tag": "narrative",
                                "render_time_ms": render_time_ms,
                            },
                        ),
                    )
                )
            continue
        if op.kind == "outline":
            text = op.text.strip()
            if text:
                render_time_ms = estimate_render_time_ms(text)
                order_raw = op.meta.get("order")
                order = int(order_raw) if order_raw is not None else None
                _emit(
                    SpeakStreamEvent(
                        kind="agent_typing",
                        text="",
                        final=False,
                        meta=render_meta(
                            "typing",
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "render_time_ms": render_time_ms,
                                "render_target": "outline",
                                "wait_reason": "render",
                            },
                        ),
                    )
                )
                sleep(_render_hold_seconds(render_time_ms))
                _emit(
                    SpeakStreamEvent(
                        kind="outline",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "outline",
                            phase=str(op.meta.get("phase") or ""),
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "tag": "outline",
                                "render_time_ms": render_time_ms,
                            },
                        ),
                    )
                )
            continue
        if op.kind == "speak":
            text = op.text.strip()
            if text:
                render_time_ms = estimate_render_time_ms(text)
                order_raw = op.meta.get("order")
                order = int(order_raw) if order_raw is not None else None
                _emit(
                    SpeakStreamEvent(
                        kind="agent_typing",
                        text="",
                        final=False,
                        meta=render_meta(
                            "typing",
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "render_time_ms": render_time_ms,
                                "render_target": "speak",
                                "wait_reason": "render",
                            },
                        ),
                    )
                )
                sleep(_render_hold_seconds(render_time_ms))
                spoken.append(text)
                _emit(
                    SpeakStreamEvent(
                        kind="speak",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "speak",
                            phase=str(op.meta.get("phase") or ""),
                            wait_ms=render_time_ms,
                            order=order,
                            extra={
                                **op.meta,
                                "tag": "speak",
                                "render_time_ms": render_time_ms,
                                "render_target": "speak",
                            },
                        ),
                    )
                )
                if session_service is not None:
                    session_service.queues.update_partial_output(sid, "\n".join(spoken).strip())
            continue
        if op.kind == "finish":
            _emit(
                SpeakStreamEvent(
                    kind="finish",
                    text="",
                    final=bool(op.final),
                    meta=render_meta("finish", extra=dict(op.meta)),
                )
            )
            continue
        raise ValueError(f"unknown OutboundOp.kind: {op.kind!r}")

    answer = "\n".join(spoken).strip() or "".join(spoken)
    if session_service is not None:
        session_service.queues.end_push(sid, partial_output=answer)
    if on_done is not None:
        on_done(sid)
    return OutboundExecuteResult(events=events, answer=answer, created_at=created_at)


def outbound_from_ops(
    session_id: str,
    ops: list[OutboundOp] | tuple[OutboundOp, ...],
    *,
    user_text: str = "",
    meta: dict[str, Any] | None = None,
) -> OutboundRequest:
    return OutboundRequest(
        session_id=session_id.strip(),
        ops=tuple(ops),
        user_text=user_text,
        meta=dict(meta or {}),
    )


def outbound_from_delivery_plan(
    plan: DeliveryPlan,
    *,
    session_id: str,
    user_text: str = "",
    include_prefix: list[OutboundOp] | None = None,
) -> OutboundRequest:
    ops: list[OutboundOp] = list(include_prefix or [])
    segments = list(plan.segments)
    total = len(segments)
    for index, segment in enumerate(segments):
        wait_ms = max(0, int(segment.wait_ms))
        if wait_ms > 0:
            ops.append(
                OutboundOp(
                    kind="wait",
                    seconds=wait_ms / 1000.0,
                    meta={
                        "delivery_segment": True,
                        "segment_index": index,
                        "segment_total": total,
                        "wait_reason": segment.wait_reason,
                        "field": "wait",
                    },
                )
            )
        text = str(segment.text or "")
        if text.strip():
            ops.append(
                OutboundOp(
                    kind="speak",
                    text=text,
                    meta={
                        "delivery_segment": True,
                        "segment_index": index,
                        "segment_total": total,
                        "wait_ms": wait_ms,
                        "planned_immediate": wait_ms == 0,
                        "field": "speak",
                    },
                )
            )
        ops.append(
            OutboundOp(
                kind="finish",
                text="",
                final=index == total - 1 and segment.continuity == "finish",
                meta={
                    "delivery_segment": True,
                    "segment_index": index,
                    "segment_total": total,
                    "continuity": segment.continuity,
                    "wait_ms": wait_ms,
                    "field": "finish",
                },
            )
        )
    return OutboundRequest(
        session_id=session_id.strip(),
        ops=tuple(ops),
        user_text=user_text,
        meta={"source": "delivery_plan", "plan_id": getattr(plan, "plan_id", "")},
    )


def outbound_from_speak_text(
    session_id: str,
    text: str,
    *,
    user_text: str = "",
    meta: dict[str, Any] | None = None,
) -> OutboundRequest:
    body = text.strip()
    ops: list[OutboundOp] = []
    if body:
        ops.append(OutboundOp(kind="speak", text=body, meta=dict(meta or {})))
    ops.append(OutboundOp(kind="finish", text="", final=True, meta=dict(meta or {})))
    return OutboundRequest(
        session_id=session_id.strip(),
        ops=tuple(ops),
        user_text=user_text,
        meta={"source": "speak_text", **(meta or {})},
    )


def outbound_from_parsed(
    session_id: str,
    *,
    thought: str = "",
    speak: str = "",
    actions: tuple[str, ...] | list[str] = (),
    observe: str = "",
    user_text: str = "",
) -> OutboundRequest:
    ops: list[OutboundOp] = []
    if thought.strip():
        ops.append(OutboundOp(kind="think", text=thought.strip(), meta={"tag": "think"}))
    for action in actions:
        text = str(action or "").strip()
        if text:
            ops.append(OutboundOp(kind="action", text=text, meta={"tag": "action"}))
    if observe.strip():
        ops.append(
            OutboundOp(
                kind="action",
                text=observe.strip(),
                meta={"tag": "observe", "observe": True},
            )
        )
    if speak.strip():
        ops.append(OutboundOp(kind="speak", text=speak.strip(), meta={"tag": "speak"}))
    ops.append(OutboundOp(kind="finish", text="", final=True))
    return OutboundRequest(
        session_id=session_id.strip(),
        ops=tuple(ops),
        user_text=user_text,
        meta={"source": "parsed"},
    )
