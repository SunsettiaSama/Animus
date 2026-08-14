from __future__ import annotations

from ..control.candidate_types import SharePlannerCandidate
from .state import ShareEventView

MAX_SHARE_PLANNER_CANDIDATES = 3

_DESIRE_RANK = {
    "none": 0,
    "mild": 1,
    "moderate": 2,
    "eager": 3,
}

__all__ = [
    "MAX_SHARE_PLANNER_CANDIDATES",
    "SharePlannerCandidate",
    "format_share_candidates",
    "select_share_candidates",
]


def _emotion_rank(event: ShareEventView) -> int:
    return _DESIRE_RANK.get(event.share_desire.value, 0)


def select_share_candidates(
    events: tuple[ShareEventView, ...],
    *,
    max_items: int = MAX_SHARE_PLANNER_CANDIDATES,
) -> tuple[SharePlannerCandidate, ...]:
    if not events:
        return ()
    cap = max(1, max_items)
    ordered = sorted(
        events,
        key=lambda event: (_emotion_rank(event), event.salience),
        reverse=True,
    )[:cap]
    return tuple(
        SharePlannerCandidate(
            planner_index=planner_index,
            queue_index=event.index,
            brief=event.brief.strip() or event.topic.strip(),
            share_desire=event.share_desire.value,
            salience=event.salience,
        )
        for planner_index, event in enumerate(ordered)
    )


def format_share_candidates(
    candidates: tuple[SharePlannerCandidate, ...],
    *,
    summary: str = "",
) -> str:
    if not candidates:
        return summary.strip()
    lines: list[str] = []
    head = summary.strip()
    if head:
        lines.append(f"摘要：{head}")
    lines.append("分享候选（按情绪强度优先列出，仅下列下标可 emit_share_index）：")
    for item in candidates:
        lines.append(
            f"- [{item.planner_index}] queue={item.queue_index} "
            f"{item.brief}（意愿：{item.share_desire}，显著性={item.salience:.2f}）"
        )
    return "\n".join(lines)
