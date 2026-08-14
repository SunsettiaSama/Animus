from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.soul.speak.io.outbound.protocol import OutboundOp, OutboundRequest
from agent.soul.speak.io.outbound.render_protocol import SpeakRenderField, render_meta
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


@dataclass
class OutboundExecuteResult:
    events: list[SpeakStreamEvent] = field(default_factory=list)
    answer: str = ""


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

    if session_service is not None:
        session_service.queues.begin_push(sid, request.user_text)
    if stream_channel is not None:
        stream_channel.begin_session(sid)

    events: list[SpeakStreamEvent] = []
    spoken: list[str] = []

    def _emit(event: SpeakStreamEvent) -> None:
        emit_fn(sid, event)
        events.append(event)

    for op in request.ops:
        if should_continue_fn is not None and not should_continue_fn(sid):
            break
        if op.kind == "think":
            text = op.text.strip()
            if text:
                _emit(
                    SpeakStreamEvent(
                        kind="thought",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "thought",
                            extra={**op.meta, "tag": "think"},
                        ),
                    )
                )
            continue
        if op.kind in ("wait", "silence"):
            seconds = min(max(0.0, float(op.seconds)), _WAIT_CAP_SEC)
            wait_ms = int(round(seconds * 1000.0))
            field: SpeakRenderField = "silence" if op.kind == "silence" else "wait"
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
                _emit(
                    SpeakStreamEvent(
                        kind="action",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "body",
                            phase=str(op.meta.get("phase") or ""),
                            extra={**op.meta, "tag": "action"},
                        ),
                    )
                )
            continue
        if op.kind == "speak":
            text = op.text.strip()
            if text:
                spoken.append(text)
                _emit(
                    SpeakStreamEvent(
                        kind="speak",
                        text=text,
                        final=False,
                        meta=render_meta(
                            "speak",
                            phase=str(op.meta.get("phase") or ""),
                            extra={**op.meta, "tag": "speak"},
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
                    text=op.text,
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
    return OutboundExecuteResult(events=events, answer=answer)


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
                text=text,
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
    ops.append(OutboundOp(kind="finish", text=body, final=True, meta=dict(meta or {})))
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
    ops.append(OutboundOp(kind="finish", text=speak.strip(), final=True))
    return OutboundRequest(
        session_id=session_id.strip(),
        ops=tuple(ops),
        user_text=user_text,
        meta={"source": "parsed"},
    )
