from __future__ import annotations

from .state.presence_state import PresenceState
from .transition.interaction import PresenceInteraction


def compose_self_narrative(
    state: PresenceState,
    interaction: PresenceInteraction,
) -> str:
    """折叠为面向 Speak 的连贯叙述：优先 recent_portrait，不含字段式当下态。"""
    portrait = state.recent_portrait.narrative.strip()
    lines: list[str] = []
    if portrait:
        lines.append(portrait)

    exp = state.expectation
    share_summary = exp.share_queue.fold_summary()
    if share_summary:
        lines.append(f"你还想跟用户分享：{share_summary}")

    if interaction.impulse_reason.strip():
        lines.append(
            f"你心里有股想说话的冲动——{interaction.impulse_reason.strip()}",
        )

    if exp.toward_user > 0.0:
        tail = f"，因为{exp.reason}" if exp.reason.strip() else ""
        lines.append(f"你想见用户{tail}")

    if exp.reply_urge > 0.0:
        lines.append("你还想再多说几句")

    if interaction.expectation.value != "none":
        lines.append(f"你对这场对话的期待是「{interaction.expectation.value}」")

    if not lines and interaction.impulse_level <= 0.0 and not share_summary:
        return ""

    return "\n".join(lines)
