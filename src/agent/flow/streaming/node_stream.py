"""节点执行器（SubAgentRunner / TaoLoop）事件 → 编排事件流。

不修改 TaoLoop 本体；由 ``FlowOrchestrator`` 注入 ``event_callback``。
产出的 dict 经 ``FlowOrchestrator._emit_raw_dict`` 派发给订阅方（与 replanner 的 dict 路径一致）。

线协议扩展：

- ``task_llm_chunk``：单次 LLM 流式分片（``index`` / ``chunk``）。
- ``task_step``：单步 Thought-Action-Observation，字段与对话侧 ``step`` 对齐（含 ``calls`` / ``output`` / ``tool_executions``）。
"""
from __future__ import annotations

from typing import Any, Callable

_WIRE_CHUNK = "task_llm_chunk"
_WIRE_STEP = "task_step"


def _is_tao_llm_chunk(ev: Any) -> bool:
    """识别 :class:`~agent.react.tao.ChunkEvent`（ duck-type，避免模块顶层 import Tao）。"""
    return hasattr(ev, "chunk") and not hasattr(ev, "action_input")


def _is_tao_step(ev: Any) -> bool:
    return hasattr(ev, "action_input") and hasattr(ev, "index") and hasattr(ev, "action")


def _chunk_wire(plan_id: str, task_id: str, ev: Any) -> dict:
    idx = getattr(ev, "index", 0)
    chunk = getattr(ev, "chunk", "") or ""
    return {
        "type": _WIRE_CHUNK,
        "plan_id": plan_id,
        "task_id": task_id,
        "index": idx,
        "chunk": chunk,
    }


def _tool_executions(ev: Any) -> list[dict]:
    calls = getattr(ev, "calls", None) or []
    if calls:
        return [{"tool": c.get("action", ""), "args": c.get("args", {})} for c in calls]
    action = getattr(ev, "action", None) or ""
    args = getattr(ev, "action_input", None)
    return [{"tool": action, "args": dict(args or {})}]


def _step_payload(ev: Any) -> dict:
    return {
        "type": "step",
        "index": int(getattr(ev, "index", 0)),
        "thought": getattr(ev, "thought", None) or "",
        "action": getattr(ev, "action", None) or "",
        "action_input": getattr(ev, "action_input", None),
        "observation": getattr(ev, "observation", None) or "",
        "calls": getattr(ev, "calls", None),
        "output": getattr(ev, "output", None) or "",
        "tool_executions": _tool_executions(ev),
    }


def make_executor_tao_stream_callback(
    *,
    plan_id: str,
    task_id: str,
    task_steps: dict[str, list[dict]],
    schedule_emit_raw: Callable[[dict], None],
) -> Callable[[Any], None]:
    """构建 ``SubAgentRunner.run_sync(..., event_callback=...)`` 的回调。

    ``schedule_emit_raw`` 须线程安全地调度到编排器所在事件循环（例如
    ``loop.call_soon_threadsafe(orch._emit_raw_dict, d)``）。
    """

    def _callback(event: Any) -> None:
        if _is_tao_llm_chunk(event):
            schedule_emit_raw(_chunk_wire(plan_id, task_id, event))
            return
        if not _is_tao_step(event):
            return
        step = _step_payload(event)
        task_steps.setdefault(task_id, []).append(step)
        schedule_emit_raw(
            {
                "type": _WIRE_STEP,
                "plan_id": plan_id,
                "task_id": task_id,
                "step": step,
            }
        )

    return _callback
