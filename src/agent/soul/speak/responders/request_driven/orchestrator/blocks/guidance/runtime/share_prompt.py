from __future__ import annotations

from .share.state import ShareComposeState


def render_share_guidance(state: ShareComposeState) -> str:
    """存在分享队列时，生成注入 system 的分享引导块。"""
    if not state.wants_share:
        return ""

    lines = [
        "你心里有想与用户分享的事情；是否分享、何时分享由你自行决定"
        "（可用 state:share 或指向索引查阅详情）。",
    ]
    summary = state.summary.strip()
    if summary:
        lines.append(f"分享摘要：{summary.rstrip('。')}。")
    if state.events:
        lines.append("待分享事项如下：")
        for event in state.events:
            desire = event.share_desire.value
            lines.append(f"- [{event.index}] {event.brief}（意愿：{desire}）")
    return " ".join(lines)
