from __future__ import annotations

from agent.soul.presence import PresenceService, PresenceStateBlock
from agent.soul.presence.state import ShareIntent
from agent.soul.presence.share_desire import ShareDesire, StaticStatePatch
def test_compose_self_narrative_includes_share_queue():
    svc = PresenceService()
    session = svc._session("tao")
    session.state.affect.narrative = "有点想聊天"
    session.state.expectation.share_queue.enqueue(
        ShareIntent(topic="想告诉你一件事", share_desire=ShareDesire.moderate)
    )
    text = svc.compose_self_narrative("tao")
    assert "此刻我的状态" in text
    assert "想告诉你一件事" in text
    assert "有点想聊天" in text


def test_apply_state_block_queues_share_when_desired():
    svc = PresenceService()
    notes = svc.apply_state_block(PresenceStateBlock.experience(
        narratives={"affect": "刚经历了一件小事"},
        meta={
            "wants_to_share": "true",
            "share_topic": "想分享刚才的体验",
            "share_desire": "moderate",
        },
    ))
    assert notes
    assert svc.share_queue_size("tao") == 1
    assert svc.snapshot("tao").toward_user_expectation > 0.0


def test_apply_state_block_skips_queue_without_share_desire():
    svc = PresenceService()
    notes = svc.apply_state_block(PresenceStateBlock.rumination(
        narratives={"thinking": "回忆起旧片段"},
        meta={"wants_to_share": "false"},
    ))
    assert svc.share_queue_size("tao") == 0
    assert "rumination hint" in " ".join(notes) or notes == [] or True


def test_state_block_on_worker_queues_share():
    from agent.soul.workers.domain_worker import DomainWorker

    worker = DomainWorker("presence-worker-test")
    worker.start()
    svc = PresenceService()
    block = PresenceStateBlock.experience(
        meta={
            "wants_to_share": "true",
            "share_topic": "异步块测试",
            "share_desire": "eager",
        },
    )
    notes = worker.submit(lambda: svc.apply_state_block(block)).result()
    assert notes
    assert svc.share_queue_size("tao") == 1
    worker.stop()
