from __future__ import annotations

from agent.soul.speak.pipelines.rhythm.contracts import RhythmPlan, ShareItem
from agent.soul.speak.pipelines.rhythm.share import (
    build_share_handoff,
    commit_share_after_speak,
)


def _queue() -> tuple[ShareItem, ...]:
    return (
        ShareItem(item_id="share-1", topic="边界草稿有重复"),
        ShareItem(item_id="share-2", topic="先留冒烟入口"),
    )


def test_build_share_handoff_by_id():
    plan = RhythmPlan(
        gate="brew",
        segments=(),
        share_tag="share",
        share_id="share-2",
    )
    handoff = build_share_handoff(plan, share_queue=_queue(), last_shared=None)
    assert handoff.active
    assert handoff.item is not None
    assert handoff.item.item_id == "share-2"
    assert handoff.queue_index == 1


def test_commit_share_pops_on_speak_only():
    queue = list(_queue())
    plan = RhythmPlan(
        gate="brew",
        segments=(),
        share_tag="share",
        share_id="share-1",
    )
    handoff = build_share_handoff(plan, share_queue=tuple(queue), last_shared=None)
    last: list[ShareItem] = []

    def pop_at(session_id: str, index: int):
        del session_id
        return queue.pop(index)

    taken = commit_share_after_speak(
        session_id="s1",
        handoff=handoff,
        pop_share_at=pop_at,
        set_last_shared=lambda item: last.append(item),
    )
    assert taken is not None
    assert taken.item_id == "share-1"
    assert len(queue) == 1
    assert last and last[0].item_id == "share-1"


def test_listen_does_not_commit_share():
    plan = RhythmPlan(gate="listen", segments=(), share_tag="none")
    handoff = build_share_handoff(plan, share_queue=_queue(), last_shared=None)
    assert not handoff.active
    taken = commit_share_after_speak(
        session_id="s1",
        handoff=handoff,
        pop_share_at=lambda sid, idx: (_ for _ in ()).throw(AssertionError("should not pop")),
        set_last_shared=lambda item: (_ for _ in ()).throw(AssertionError("no last")),
    )
    assert taken is None
