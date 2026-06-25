from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent
from agent.soul.speak.pipelines.request_driven.orchestrator.prompt_trace import get_prompt_trace

if TYPE_CHECKING:
    from agent.soul.speak.io.outbound.stream import SpeakStreamChannel
    from agent.soul.speak.session import SpeakSessionService

    from ..state.core.delivery import DeliveryPlan


TYPING_LEAD_MIN_MS = 80
TYPING_LEAD_MAX_MS = 120


@dataclass
class DeliveryProgress:
    segment_index: int = 0
    segment_total: int = 0


class DeliveryExecutor:
    """消费 DeliveryPlan：按段 wait + agent_typing + speak + finish 推送。"""

    def __init__(
        self,
        *,
        emit_fn: Callable[[str, SpeakStreamEvent], None],
        on_segment_progress: Callable[[str, int, int], None] | None = None,
        on_done: Callable[[str], None] | None = None,
        should_continue_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._emit = emit_fn
        self._on_segment_progress = on_segment_progress
        self._on_done = on_done
        self._should_continue_fn = should_continue_fn
        self._progress: dict[str, DeliveryProgress] = {}

    def progress(self, session_id: str) -> tuple[int, int]:
        item = self._progress.get(session_id.strip())
        if item is None:
            return 0, 0
        return item.segment_index, item.segment_total

    def execute(
        self,
        plan: DeliveryPlan,
        *,
        session_service: SpeakSessionService,
        session_id: str,
        user_text: str = "",
        stream_channel: SpeakStreamChannel | None = None,
    ) -> list[SpeakStreamEvent]:
        sid = session_id.strip()
        if plan.is_empty:
            return []
        segments = list(plan.segments)
        total = len(segments)
        trace = get_prompt_trace()
        trace.emit_event(
            sid,
            label="delivery_plan_execute",
            turn_index=plan.turn_index,
            payload={"plan": plan.snapshot(), "user_text": user_text},
        )
        self._progress[sid] = DeliveryProgress(segment_index=0, segment_total=total)
        session_service.queues.begin_push(sid, user_text)
        if stream_channel is not None:
            stream_channel.begin_session(sid)
        events: list[SpeakStreamEvent] = []
        delivered_text: list[str] = []
        for index, segment in enumerate(segments):
            if self._should_continue_fn is not None and not self._should_continue_fn(sid):
                break
            self._progress[sid].segment_index = index
            if self._on_segment_progress is not None:
                self._on_segment_progress(sid, index, total)
            wait_ms = max(0, int(segment.wait_ms))
            trace.emit_event(
                sid,
                label="delivery_segment",
                turn_index=plan.turn_index,
                payload={
                    "segment_index": index,
                    "segment_total": total,
                    "text": segment.text,
                    "wait_ms": wait_ms,
                    "wait_reason": segment.wait_reason,
                    "continuity": segment.continuity,
                },
            )
            if wait_ms > 0:
                lead = min(TYPING_LEAD_MAX_MS, max(TYPING_LEAD_MIN_MS, wait_ms // 10))
                typing_event = SpeakStreamEvent(
                    kind="agent_typing",
                    text="",
                    meta={
                        "delivery_segment": True,
                        "segment_index": index,
                        "segment_total": total,
                        "wait_ms": wait_ms,
                        "wait_reason": segment.wait_reason,
                        "planned_immediate": False,
                        "trace_only_reason": segment.wait_reason,
                    },
                )
                self._emit(sid, typing_event)
                events.append(typing_event)
                time.sleep(max(0, wait_ms - lead) / 1000.0)
            speak_event = SpeakStreamEvent(
                kind="speak",
                text=segment.text,
                meta={
                    "delivery_segment": True,
                    "segment_index": index,
                    "segment_total": total,
                    "wait_ms": wait_ms,
                    "planned_immediate": wait_ms == 0,
                },
            )
            self._emit(sid, speak_event)
            events.append(speak_event)
            delivered_text.append(segment.text)
            partial = "\n".join(delivered_text).strip()
            session_service.queues.update_partial_output(sid, partial)
            finish_event = SpeakStreamEvent(
                kind="finish",
                text=segment.text,
                final=index == total - 1 and segment.continuity == "finish",
                meta={
                    "delivery_segment": True,
                    "segment_index": index,
                    "segment_total": total,
                    "continuity": segment.continuity,
                    "wait_ms": wait_ms,
                },
            )
            self._emit(sid, finish_event)
            events.append(finish_event)
        session_service.queues.end_push(sid, partial_output="\n".join(delivered_text).strip())
        self._progress.pop(sid, None)
        if self._on_done is not None:
            self._on_done(sid)
        return events
