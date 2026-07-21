from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contracts import RhythmPlan, ShareHandOff, ShareItem

PeekShareFn = Callable[[str], list[dict[str, object]]]
PopShareAtFn = Callable[[str, int], Any]


def share_items_from_peek(rows: list[dict[str, object]]) -> tuple[ShareItem, ...]:
    items: list[ShareItem] = []
    for idx, row in enumerate(rows):
        topic = str(row.get("topic") or "").strip()
        if not topic:
            continue
        item_id = str(row.get("item_id") or row.get("id") or f"share-{idx + 1}").strip()
        items.append(
            ShareItem(
                item_id=item_id,
                topic=topic,
                detail=str(row.get("detail") or "").strip(),
                source=str(row.get("source") or "").strip(),
                salience=float(row.get("salience") or 0.0),
            )
        )
    return tuple(items)


def resolve_share_index(queue: tuple[ShareItem, ...], ref: str) -> int | None:
    token = ref.strip()
    if not token:
        return 0 if queue else None
    for idx, item in enumerate(queue):
        if item.item_id == token:
            return idx
    if token.isdigit():
        idx = int(token) - 1
        if 0 <= idx < len(queue):
            return idx
    for idx, item in enumerate(queue):
        if token in item.topic or token in item.one_line():
            return idx
    return None


def build_share_handoff(
    plan: RhythmPlan,
    *,
    share_queue: tuple[ShareItem, ...],
    last_shared: ShareItem | None,
) -> ShareHandOff:
    tag = plan.share_tag
    if tag == "none":
        return ShareHandOff(tag="none")
    if tag == "expand":
        item = last_shared
        if item is None and plan.share_id.strip():
            idx = resolve_share_index(share_queue, plan.share_id)
            if idx is not None:
                item = share_queue[idx]
        if item is None:
            return ShareHandOff(tag="none")
        return ShareHandOff(tag="expand", item=item, expand_text="")
    idx = resolve_share_index(share_queue, plan.share_id)
    if idx is None:
        return ShareHandOff(tag="none")
    return ShareHandOff(tag="share", item=share_queue[idx], queue_index=idx)


def commit_share_after_speak(
    *,
    session_id: str,
    handoff: ShareHandOff,
    pop_share_at: PopShareAtFn | None,
    set_last_shared: Callable[[ShareItem], None],
) -> ShareItem | None:
    if not handoff.active or handoff.item is None:
        return None
    if handoff.tag == "share":
        if handoff.queue_index is None or pop_share_at is None:
            set_last_shared(handoff.item)
            return handoff.item
        popped = pop_share_at(session_id, handoff.queue_index)
        if popped is None:
            return None
        topic = getattr(popped, "topic", "") or handoff.item.topic
        item = ShareItem(
            item_id=handoff.item.item_id,
            topic=str(topic).strip() or handoff.item.topic,
            detail=handoff.item.detail,
            source=str(getattr(popped, "source", "") or handoff.item.source),
            salience=float(getattr(popped, "salience", handoff.item.salience) or 0.0),
        )
        set_last_shared(item)
        return item
    if handoff.tag == "expand":
        set_last_shared(handoff.item)
        return handoff.item
    return None
