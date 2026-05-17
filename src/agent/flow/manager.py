"""Flow 与前端 SSE / WebUI 的桥接：序列化编排事件并可选择缓冲后 flush。

``FlowOrchestrator`` 等在 worker 线程与 asyncio 事件循环两边都会触发
``subscribe`` 回调；对 ``asyncio.Queue`` 的 ``put_nowait`` 须在对应循环上调度。
``FlowFrontendBridge`` 用 ``loop.call_soon_threadsafe`` 将 ``broadcast_fn`` 派发到主循环，
避免跨线程直接向 Queue 投递导致的不确定行为。

可选 ``buffer_max > 1`` 时先入队，再由 ``flush()`` 或缓冲区满时一次发出，
以降低超高频事件（如 task_step）对前端的冲刷；默认 ``buffer_max=1`` 即立即下发（每次 emit 后即视为 flush）。
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ── 序列化：编排事件 → 前端 JSON-able dict ────────────────────────────────────


def mirror_plan_flow_id(data: dict) -> dict:
    """与 Web 侧 ``flow_id`` 对齐（与 historical ``plan_id`` 镜像）。"""
    if "plan_id" in data and "flow_id" not in data:
        data = dict(data)
        data["flow_id"] = data["plan_id"]
    return data


def serialize_plan_event(event: Any) -> dict:
    """``PlanEvent`` / ``OrchestratorEvent`` / ``dict`` → 发往 SSE 的 payload。"""
    if isinstance(event, dict):
        return mirror_plan_flow_id(event)
    from agent.flow.base.orchestration import OrchestratorEvent

    if isinstance(event, OrchestratorEvent):
        return mirror_plan_flow_id(
            {"type": event.kind.replace(".", "_"), "plan_id": event.plan_id, **event.payload}
        )

    from agent.flow.cluster.event import (
        HumanPatchEvent,
        LifecycleStateEvent,
        LogLineEvent,
        NodeExpansionRequestEvent,
        PlanAbortEvent,
        PlanCompleteEvent,
        PlanStartEvent,
        PlannerStepEvent,
        ReplanEvent,
        ReplannerCompleteEvent,
        ReplannerStartEvent,
        ReplannerThinkingEvent,
        SnapshotEvent,
        TaskCompleteEvent,
        TaskFailedEvent,
        TaskRunningEvent,
        TaskSkippedEvent,
        TaskStartEvent,
        TaskStepEvent,
    )
    if isinstance(event, PlanStartEvent):
        return mirror_plan_flow_id(
            {"type": "plan_start", "plan_id": event.plan_id, "title": event.title, "task_count": event.task_count}
        )
    if isinstance(event, TaskStartEvent):
        return mirror_plan_flow_id(
            {
                "type": "task_start",
                "plan_id": event.plan_id,
                "task_id": event.task_id,
                "module": event.module,
                "profile": event.profile,
            }
        )
    if isinstance(event, TaskRunningEvent):
        return mirror_plan_flow_id({"type": "task_running", "plan_id": event.plan_id, "task_id": event.task_id})
    if isinstance(event, TaskCompleteEvent):
        return mirror_plan_flow_id(
            {"type": "task_complete", "plan_id": event.plan_id, "task_id": event.task_id, "result_preview": event.result_preview}
        )
    if isinstance(event, TaskFailedEvent):
        return mirror_plan_flow_id({"type": "task_failed", "plan_id": event.plan_id, "task_id": event.task_id, "error": event.error})
    if isinstance(event, TaskSkippedEvent):
        return mirror_plan_flow_id({"type": "task_skipped", "plan_id": event.plan_id, "task_id": event.task_id, "reason": event.reason})
    if isinstance(event, ReplanEvent):
        return mirror_plan_flow_id(
            {
                "type": "replan",
                "plan_id": event.plan_id,
                "trigger": event.trigger,
                "decision": event.decision,
                "patches_count": event.patches_count,
                "cycle": event.cycle,
            }
        )
    if isinstance(event, HumanPatchEvent):
        return mirror_plan_flow_id(
            {"type": "human_patch", "plan_id": event.plan_id, "patches_count": event.patches_count, "patch_ops": event.patch_ops}
        )
    if isinstance(event, SnapshotEvent):
        return mirror_plan_flow_id(
            {"type": "snapshot", "plan_id": event.plan_id, "snapshot_id": event.snapshot_id, "trigger": event.trigger}
        )
    if isinstance(event, PlanCompleteEvent):
        return mirror_plan_flow_id({"type": "plan_complete", "plan_id": event.plan_id, "conclusion": event.conclusion})
    if isinstance(event, PlanAbortEvent):
        return mirror_plan_flow_id({"type": "plan_abort", "plan_id": event.plan_id, "reason": event.reason})
    if isinstance(event, LifecycleStateEvent):
        return mirror_plan_flow_id({"type": "lifecycle_state", "plan_id": event.plan_id, "state": event.state})
    if isinstance(event, TaskStepEvent):
        return mirror_plan_flow_id({"type": "task_step", "plan_id": event.plan_id, "task_id": event.task_id, "step": event.step})
    if isinstance(event, PlannerStepEvent):
        return mirror_plan_flow_id(
            {
                "type": "planner_step",
                "plan_id": event.plan_id,
                "phase": event.phase,
                "step_index": event.step_index,
                "thought": event.thought,
                "action": event.action,
                "observation": event.observation,
            }
        )
    if isinstance(event, ReplannerStartEvent):
        return mirror_plan_flow_id({"type": "replanner_start", "plan_id": event.plan_id, "trigger": event.trigger, "cycle": event.cycle})
    if isinstance(event, ReplannerCompleteEvent):
        return mirror_plan_flow_id(
            {
                "type": "replanner_complete",
                "plan_id": event.plan_id,
                "decision": event.decision,
                "reason": event.reason,
                "patches_count": event.patches_count,
            }
        )
    if isinstance(event, ReplannerThinkingEvent):
        return mirror_plan_flow_id(
            {"type": "replanner_thinking", "plan_id": event.plan_id, "stage": event.stage, "cycle": event.cycle}
        )
    if isinstance(event, NodeExpansionRequestEvent):
        return mirror_plan_flow_id(
            {
                "type": "node_expansion_request",
                "plan_id": event.plan_id,
                "task_id": event.task_id,
                "reason": event.reason,
                "suggested_subtasks": event.suggested_subtasks,
            }
        )
    if isinstance(event, LogLineEvent):
        return mirror_plan_flow_id(
            {"type": "log_line", "plan_id": event.plan_id, "level": event.level, "event": event.event, **event.payload}
        )
    return {"type": "unknown", "repr": repr(event)}


def sse_keepalive_ping_payload() -> dict:
    """可选：通过 SSE 发送注释等价负载，触发连接侧 flush（减少对 ``task_step`` 的单独帧依赖）。"""
    return {"type": "sse_ping", "_comment": ": keep-alive"}


# ── 桥接 ───────────────────────────────────────────────────────────────────────


@dataclass
class FlowFrontendBridgeConfig:
    """前端桥接缓冲。

    ``buffer_max == 1``：每条事件序列化后立即经 ``broadcast_fn`` 下发（默认，等价 continuous flush）。
    ``buffer_max > 1``：先写入内部缓冲，缓冲区满或调用 ``flush()`` 时一并下发；
    ``coalesce_as_batch`` 为 True 时单条 SSE 载荷为 ``{type: flow_batch, events: [...]}``，
    为 False 时按顺序多次调用 ``broadcast_fn``。
    """

    buffer_max: int = 1
    coalesce_as_batch: bool = True


@dataclass
class FlowFrontendBridge:
    broadcast_fn: Callable[[dict], None]
    main_loop: Any | None = None
    config: FlowFrontendBridgeConfig = field(default_factory=FlowFrontendBridgeConfig)
    _pending: list[dict] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def plan_event_callback(self) -> Callable[[Any], None]:
        """可供 ``orchestrator.subscribe(...)`` 的回调。"""

        def _cb(event: Any) -> None:
            self.emit(event)

        return _cb

    def emit(self, raw: Any) -> None:
        """序列化并投递（按需缓冲）；``buffer_max==1`` 时等同立即 flush。"""
        payload = serialize_plan_event(raw)
        bm = max(1, int(self.config.buffer_max))
        if bm == 1:
            self._schedule_broadcast(payload)
            return
        with self._lock:
            self._pending.append(payload)
            if len(self._pending) >= bm:
                batch = list(self._pending)
                self._pending.clear()
            else:
                batch = []
        if batch:
            self._emit_batch(batch)

    def flush(self) -> None:
        """排空缓冲队列并下发（在 ``buffer_max > 1`` 时常与周期调用或收尾配合使用）。"""
        with self._lock:
            batch = list(self._pending)
            self._pending = []
        if batch:
            self._emit_batch(batch)

    def emit_raw_dict(self, data: dict) -> None:
        """已构造好的前端 dict（会做 ``mirror_plan_flow_id``）。"""
        self._schedule_broadcast(mirror_plan_flow_id(dict(data)))

    def _emit_batch(self, batch: list[dict]) -> None:
        if not batch:
            return
        if self.config.coalesce_as_batch:
            self._schedule_broadcast(
                mirror_plan_flow_id({"type": "flow_batch", "events": batch, "count": len(batch)})
            )
            return
        for item in batch:
            self._schedule_broadcast(item)

    def _schedule_broadcast(self, payload: dict) -> None:
        def _deliver() -> None:
            self.broadcast_fn(payload)

        loop = self.main_loop
        if loop is not None:
            loop.call_soon_threadsafe(_deliver)
            return
        _deliver()
