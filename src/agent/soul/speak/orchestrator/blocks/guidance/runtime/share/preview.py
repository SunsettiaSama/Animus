from __future__ import annotations

from .state import ShareComposeState


def format_share_preview(state: ShareComposeState) -> str:
    """供引导规划器阅读的分享队列摘要（不直接注入 system）。"""
    if not state.wants_share:
        return ""
    lines: list[str] = []
    summary = state.summary.strip()
    if summary:
        lines.append(f"摘要：{summary}")
    if state.events:
        lines.append("待分享事项：")
        for event in state.events:
            desire = event.share_desire.value
            lines.append(f"- [{event.index}] {event.brief}（意愿：{desire}）")
    return "\n".join(lines)
