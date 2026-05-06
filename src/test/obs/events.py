from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMCallEvent:
    session_id: str
    ts: float
    model: str
    call_type: str          # "generate" | "stream"
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    ttfb_ms: float          # for non-streaming equals latency_ms
    token_source: str       # "api" | "estimated"
    messages_snapshot: list[dict] = field(default_factory=list)


@dataclass
class ToolCallEvent:
    session_id: str
    ts: float
    step_index: int
    tool_name: str
    latency_ms: float
    input_summary: str
    output_summary: str


@dataclass
class SessionEvent:
    session_id: str
    ts: float
    event_type: str         # "start" | "finish" | "max_steps"
    question_summary: str
    total_steps: int
    answer_summary: str


@dataclass
class ParseEvent:
    session_id: str
    ts: float
    step_index: int
    event_type: str         # "retry_l2" | "repair_l3"
    diagnosis: str
