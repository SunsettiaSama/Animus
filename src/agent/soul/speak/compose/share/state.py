from __future__ import annotations

from dataclasses import dataclass

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.state.dynamic.expectation.package import ShareFoldedPackage, fold_share_queue
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue


@dataclass(frozen=True)
class ShareEventView:
    """队列中单条待分享事件（compose 只读视图）。"""

    index: int
    topic: str
    share_desire: ShareDesire
    source: str
    salience: float
    brief: str


@dataclass(frozen=True)
class ShareComposeState:
    """分享意愿 compose 状态：队列事件 + 拼接摘要。"""

    wants_share: bool
    summary: str
    events: tuple[ShareEventView, ...]
    package: ShareFoldedPackage

    @property
    def count(self) -> int:
        return len(self.events)


def _read_share_queue(presence_snap) -> ShareIntentQueue:
    return ShareIntentQueue.from_dict(
        (presence_snap.state.expectation.to_dict() or {}).get("share_queue"),
    )


def _build_event_views(queue: ShareIntentQueue) -> tuple[ShareEventView, ...]:
    return tuple(
        ShareEventView(
            index=index,
            topic=intent.topic,
            share_desire=intent.share_desire,
            source=intent.source,
            salience=intent.salience,
            brief=intent.topic.strip(),
        )
        for index, intent in enumerate(queue.items)
    )


def collect_share_state(presence_snap) -> ShareComposeState:
    """从 presence 快照读取分享队列并拼接摘要。"""
    queue = _read_share_queue(presence_snap)
    interaction = presence_snap.interaction
    package = fold_share_queue(queue, interaction)
    summary = package.summary.strip()
    share_desire = interaction.share_desire
    wants_share = (
        not queue.is_empty()
        or share_desire != ShareDesire.none
        or bool(summary)
    )
    return ShareComposeState(
        wants_share=wants_share,
        summary=summary,
        events=_build_event_views(queue),
        package=package,
    )
