from __future__ import annotations

from agent.soul.speak.session.queue.types import InterruptContext


def render_interrupt_system_block(ctx: InterruptContext) -> str:
    lines = [
        "用户在 agent 尚未完成 outward 推送时又发送了新消息。",
        f"用户最新输入：{ctx.new_user_text.strip()}",
    ]
    if ctx.previous_user_text.strip():
        lines.append(f"被打断的上一轮用户输入：{ctx.previous_user_text.strip()}")
    if ctx.partial_agent_output.strip():
        lines.append(f"尚未完成推送的 agent 输出片段：{ctx.partial_agent_output.strip()}")
    if ctx.suspended_compose_count > 0:
        lines.append(
            f"已暂停 compose 队列 {ctx.suspended_compose_count} 项"
            f"（share/recall/append 等后续推送已挂起）。"
        )
    if ctx.suspended_compose_summary.strip():
        lines.append(f"队列快照：{ctx.suspended_compose_summary.strip()}")
    if ctx.queue_decision_maintain is not None:
        action = "维持" if ctx.queue_decision_maintain else "丢弃"
        lines.append(f"队列决策（异步已完成）：{action}挂起队列。")
        if ctx.queue_decision_thought.strip():
            lines.append(f"决策理由：{ctx.queue_decision_thought.strip()}")
        if ctx.queue_decision_reorder is not None:
            order = ",".join(str(index) for index in ctx.queue_decision_reorder)
            lines.append(f"恢复顺序：{order}")
    lines.extend([
        "请先回应用户最新输入；队列处置已由独立决策轮完成，无需在本轮 think 中重复判断。",
        "按正常轮次状态输出 finish / append / share / recall 即可。",
    ])
    return "\n".join(lines)
