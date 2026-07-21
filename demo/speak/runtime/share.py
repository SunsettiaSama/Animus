from __future__ import annotations

from typing import cast

from ..contracts import RhythmPlan, ShareHandOff
from ..io.share_expand import NullShareExpand, ShareExpandPort
from ..stage import StageState
from ..stage.models import ShareEvent


def resolve_share_ref(stage: StageState, ref: str) -> ShareEvent | None:
    """按 id / 1-based 序号 / 标题子串解析队列中的条目（不拷贝队列）。"""
    token = ref.strip()
    if not token:
        return stage.peek_share()
    for event in stage.share_queue:
        if event.event_id == token:
            return event
    if token.isdigit():
        idx = int(token) - 1
        if 0 <= idx < len(stage.share_queue):
            return stage.share_queue[idx]
    for event in stage.share_queue:
        if token in event.title or token in event.one_line():
            return event
    return None


def build_share_handoff(
    stage: StageState,
    plan: RhythmPlan,
    *,
    expander: ShareExpandPort | None = None,
) -> ShareHandOff:
    tag = plan.share_tag
    if tag == "none":
        return ShareHandOff(tag="none")

    if tag == "expand":
        event = stage.last_shared
        if event is None and plan.share_id.strip():
            event = resolve_share_ref(stage, plan.share_id)
        if event is None:
            return ShareHandOff(tag="none")
        port = expander or NullShareExpand()
        return ShareHandOff(
            tag="expand",
            event=event,
            expand_text=port.retrieve(event),
        )

    event = resolve_share_ref(stage, plan.share_id)
    if event is None:
        return ShareHandOff(tag="none")
    return ShareHandOff(tag="share", event=event)


def commit_share_after_speak(stage: StageState, handoff: ShareHandOff) -> ShareEvent | None:
    """
    开口成功后消费队列条目（compose 不碰队列）。

    share：出队并记入 last_shared，供下次 expand。
    expand：不再出队（已出过），只刷新 last_shared 指向。
    """
    if not handoff.active or handoff.event is None:
        return None
    if handoff.tag == "share":
        return stage.consume_share(handoff.event.event_id)
    if handoff.tag == "expand":
        event = cast(ShareEvent, handoff.event)
        stage.last_shared = event
        return event
    return None
