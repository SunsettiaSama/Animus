from __future__ import annotations

from dataclasses import dataclass

from agent.soul.presence.share_desire import ShareDesire, max_share_desire

from .queue import ShareIntent, ShareIntentQueue


@dataclass(frozen=True)
class ShareFoldedPackage:
    """分享话题折叠包（出站 speak 请求载荷）。"""

    summary: str
    entries: tuple[ShareIntent, ...]
    peak_salience: float
    total_salience: float
    peak_share_desire: ShareDesire
    count: int

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "count": self.count,
            "peak_salience": self.peak_salience,
            "total_salience": self.total_salience,
            "peak_share_desire": self.peak_share_desire.value,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def fold_share_queue(
    queue: ShareIntentQueue,
    interaction,
    *,
    fallback_summary: str = "",
) -> ShareFoldedPackage:
    summary = (
        queue.fold_summary()
        or fallback_summary.strip()
        or interaction.impulse_reason.strip()
    )
    if queue.is_empty():
        return ShareFoldedPackage(
            summary=summary,
            entries=(),
            peak_salience=0.0,
            total_salience=0.0,
            peak_share_desire=interaction.share_desire,
            count=0,
        )

    peak_desire = max_share_desire(queue.peak_share_desire(), interaction.share_desire)
    return ShareFoldedPackage(
        summary=summary,
        entries=tuple(queue.items),
        peak_salience=max((item.salience for item in queue.items), default=0.0),
        total_salience=sum(item.salience for item in queue.items),
        peak_share_desire=peak_desire,
        count=len(queue.items),
    )
