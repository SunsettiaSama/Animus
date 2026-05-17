from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class TimelineReadArgs(BaseModel):
    date: str = Field(
        "",
        description=(
            "要读取的日期，格式 YYYY-MM-DD（如 2026-05-08）。"
            "留空则读取今天的时间线事件。"
        ),
    )
    event_types: str = Field(
        "",
        description=(
            "过滤的事件类型，逗号分隔（如 'conversation,scheduled_task'）。"
            "留空则返回全部类型。"
        ),
    )
    limit: int = Field(
        50,
        ge=1,
        le=200,
        description="最多返回的事件条数（默认50，最大200）",
    )


class TimelineReadAction(BaseAction):
    name: str = "timeline_read"
    description: str = (
        "读取时间线事件日志，查看 Agent 在某天做了什么（对话、调度任务完成、工具调用等）。"
        "参数：date（YYYY-MM-DD，留空=今天），event_types（过滤类型，逗号分隔，留空=全部），"
        "limit（最多返回条数，默认50）。"
        "返回时间线事件摘要，按时间排序。"
    )
    args_model: ClassVar[type[BaseModel]] = TimelineReadArgs

    timeline: Any = None  # TimelineService（或兼容 append/read/make_tool_sink 的对象）

    def execute(
        self,
        date: str = "",
        event_types: str = "",
        limit: int = 50,
        **kwargs,
    ) -> str:
        if self.timeline is None:
            return "时间线未初始化。"

        events = self.timeline.read(date or None)

        if event_types:
            allowed = {t.strip() for t in event_types.split(",") if t.strip()}
            events = [e for e in events if e.get("type") in allowed]

        events = events[:limit]

        if not events:
            label = date or "今天"
            return f"{label} 的时间线为空（无事件记录）。"

        lines: list[str] = [f"时间线 [{date or '今天'}]，共 {len(events)} 条事件：", ""]
        for ev in events:
            ts = ev.get("ts", "")
            time_label = ts[11:16] if len(ts) >= 16 else ts
            ev_type = ev.get("type", "unknown")
            payload = ev.get("payload", {})

            if ev_type == "conversation":
                summary = payload.get("summary", payload.get("question", ""))[:100]
                lines.append(f"[{time_label}] 对话  {summary}")
            elif ev_type == "scheduled_task":
                task_name = payload.get("task_name", "")
                answer_preview = payload.get("answer", "")[:80]
                lines.append(f"[{time_label}] 调度任务 [{task_name}]  {answer_preview}")
            elif ev_type == "tool_call":
                action = payload.get("action", "")
                lines.append(f"[{time_label}] 工具调用  {action}")
            elif ev_type in ("plan_event", "flow_event"):
                lines.append(f"[{time_label}] Flow/计划事件  {str(payload)[:80]}")
            else:
                lines.append(f"[{time_label}] {ev_type}  {str(payload)[:80]}")

        return "\n".join(lines)
