from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator

CHANNEL_DIALOG = "dialog"
CHANNEL_SUB_AGENT = "sub_agent"
CHANNEL_WORKFLOW = "workflow"


def envelope_dialog_wire(d: dict) -> dict:
    o = dict(d)
    if o.get("channel") is None:
        o["channel"] = CHANNEL_DIALOG
    return o


def envelope_sub_agent_wire(d: dict) -> dict:
    o = dict(d)
    o["channel"] = CHANNEL_SUB_AGENT
    return o


def envelope_workflow_event(d: dict) -> dict:
    o = dict(d)
    if o.get("channel") is None:
        o["channel"] = CHANNEL_WORKFLOW
    return o


def sub_agent_event_to_wire_dict(event: Any) -> dict | None:
    from agent.react.tao import (
        SubAgentChunkEvent,
        SubAgentErrorEvent,
        SubAgentFinishEvent,
        SubAgentStartEvent,
        SubAgentStepEvent,
    )
    if isinstance(event, SubAgentStartEvent):
        return {"type": "sub_start", "action": event.action, "instruction": event.instruction}
    if isinstance(event, SubAgentChunkEvent):
        return {"type": "sub_chunk", "index": event.index, "chunk": event.chunk}
    if isinstance(event, SubAgentStepEvent):
        calls = event.calls or []
        tool_executions = (
            [{"tool": c.get("action", ""), "args": c.get("args", {})} for c in calls]
            if calls
            else [{"tool": event.action, "args": dict(event.action_input or {})}]
        )
        return {
            "type": "sub_step",
            "index": event.index,
            "thought": event.thought,
            "action": event.action,
            "action_input": event.action_input,
            "observation": event.observation,
            "is_error": event.is_error,
            "calls": event.calls,
            "tool_executions": tool_executions,
        }
    if isinstance(event, SubAgentFinishEvent):
        return {"type": "sub_finish", "answer": event.answer}
    if isinstance(event, SubAgentErrorEvent):
        return {"type": "sub_error", "error": event.error}
    return None


def tao_event_to_wire_dict(event: Any) -> dict | None:
    from agent.react.tao import (
        ApprovalRequestEvent,
        ChunkEvent,
        FinishEvent,
        MaxStepsEvent,
        PromptPreviewEvent,
        RetryEvent,
        StepEvent,
        StepStartEvent,
    )
    if isinstance(event, PromptPreviewEvent):
        return {"type": "prompt_preview", "messages": event.messages}
    if isinstance(event, StepStartEvent):
        return {"type": "step_start", "index": event.index}
    if isinstance(event, RetryEvent):
        return {"type": "retry", "index": event.index, "reason": event.reason}
    if isinstance(event, ChunkEvent):
        return {"type": "chunk", "index": event.index, "chunk": event.chunk}
    if isinstance(event, StepEvent):
        calls = event.calls or []
        tool_executions = (
            [{"tool": c.get("action", ""), "args": c.get("args", {})} for c in calls]
            if calls
            else [{"tool": event.action, "args": dict(event.action_input or {})}]
        )
        return {
            "type": "step",
            "index": event.index,
            "thought": event.thought,
            "action": event.action,
            "action_input": event.action_input,
            "observation": event.observation,
            "calls": event.calls,
            "output": event.output,
            "tool_executions": tool_executions,
        }
    if isinstance(event, FinishEvent):
        return {"type": "finish", "answer": event.answer}
    if isinstance(event, MaxStepsEvent):
        return {"type": "max_steps", "max_steps": event.max_steps}
    if isinstance(event, ApprovalRequestEvent):
        return {
            "type": "approval_request",
            "request_id": event.request_id,
            "tool_name": event.tool_name,
            "args": event.args,
            "risk_level": event.risk_level,
            "reason": event.reason,
            "deadline_secs": event.deadline_secs,
        }
    return sub_agent_event_to_wire_dict(event)


def merge_chunk_stream_to_wire_dicts(
    tao_events: Iterable[Any],
    *,
    mode: Any = "chunk",
    live_flush_n: int = 4,
) -> Iterator[dict]:
    """兼容入口：委托 :class:`ConversationWireComposer` 实现。"""
    from agent.adapters.react_stream import composer_for_mode, coerce_output_mode

    raw = mode.value if hasattr(mode, "value") else mode
    comp = composer_for_mode(coerce_output_mode(str(raw)), live_flush_n=live_flush_n)
    yield from comp.iter_dialog_messages(tao_events)


def wire_sink_for_sub_agent(queue_put: Callable[[dict], None]) -> Callable[[Any], None]:
    def _sink(ev: Any) -> None:
        msg = sub_agent_event_to_wire_dict(ev)
        if msg is not None:
            queue_put(envelope_sub_agent_wire(msg))

    return _sink
