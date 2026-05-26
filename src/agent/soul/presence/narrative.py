from __future__ import annotations

from .state.presence_state import PresenceState
from .transition.interaction import PresenceInteraction


def compose_self_narrative(
    state: PresenceState,
    interaction: PresenceInteraction,
) -> str:
    """将当下态各维度与分享队列折叠为一段第一人称自我叙述。"""
    if state.is_empty() and interaction.impulse_level <= 0.0:
        share_summary = state.expectation.share_queue.fold_summary()
        if not share_summary:
            return ""

    lines: list[str] = ["此刻我的状态是这样的："]
    body = state.render()
    if body:
        lines.append(body)

    exp = state.expectation
    share_summary = exp.share_queue.fold_summary()
    if share_summary:
        lines.append(f"**想与用户分享** {share_summary}")

    if interaction.impulse_reason.strip():
        lines.append(
            f"**说话冲动** {interaction.impulse_reason.strip()} "
            f"（强度 {interaction.impulse_level:.2f}）"
        )

    if exp.toward_user > 0.0:
        tail = f"：{exp.reason}" if exp.reason.strip() else ""
        lines.append(f"**想见用户** 期待值 {exp.toward_user:.2f}{tail}")

    if exp.reply_urge > 0.0:
        lines.append(f"**还想多说几句** 回复欲望 {exp.reply_urge:.2f}")

    if interaction.expectation.value != "none":
        lines.append(f"**会话期待** {interaction.expectation.value}")

    return "\n".join(lines)
