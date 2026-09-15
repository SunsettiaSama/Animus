"""2c/2d 配套测试：角色开口决策 + 用户轮信号 + 剧情卡片双段。

跑法：cd src && python -m pytest test/soul/storybus/test_story_policy_cards.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.life.story import StoryCardStore  # noqa: E402
from agent.soul.speak.performance.policy import (  # noqa: E402
    HOLD,
    PERFORM_NOW,
    SILENCE,
    BeatOpeningPolicy,
)
from agent.soul.storybus import BeatDraft, PerformanceHint, StoryProgressSync  # noqa: E402
from agent.soul.wiring.story import (  # noqa: E402
    ensure_story_runtime,
    send_story_signal,
)


class _SoulStub:
    def __getattr__(self, name):
        raise AttributeError(name)


class _FakeSpeakSoul:
    """speak 就绪的假 soul：enqueue 恒成功。"""

    class _Speak:
        def enqueue_agent_outbound(self, payload):
            return {"ok": True, "delivered": True}

    def _ensure_speak_service(self):
        return self._Speak()


# ── 开口决策（R7） ──────────────────────────────────────────────────────────

def _draft(desire=0.5, urgency="normal"):
    return BeatDraft(
        narrative="她想分享黄昏的散步",
        channels=("main",),
        hint=PerformanceHint(urgency=urgency, share_desire=desire),
    )


def test_policy_branches():
    p = BeatOpeningPolicy()
    assert p.decide(_draft(), speak_ready=False).action == HOLD
    assert p.decide(_draft(), speak_ready=True, user_busy=True).action == HOLD
    assert p.decide(_draft(desire=0.9), speak_ready=True).action == PERFORM_NOW
    assert p.decide(_draft(urgency="eager", desire=0.4), speak_ready=True).action == PERFORM_NOW
    d = p.decide(_draft(desire=0.2, urgency="calm"), speak_ready=True)
    assert d.action == SILENCE
    assert p.decide(_draft(desire=0.5), speak_ready=True).action == PERFORM_NOW  # 默认开口
    assert p.salience_warrants_rewrite(0.75) and not p.salience_warrants_rewrite(0.5)


def test_bridge_silence_path_ack():
    """低欲望 + calm → 角色沉默（silenced，不是失败）。"""
    soul = _SoulStub()
    rt = ensure_story_runtime(soul)
    rt.ensure_inbox()
    n = rt.emit_drafts([_draft(desire=0.2, urgency="calm")])
    assert n == 1
    held = rt.ledger.held()
    assert len(held) == 1
    assert rt.ledger.state_of(held[0].beat_id) == "held"   # silenced → held（可改期/归档）


def test_bridge_perform_path_ack():
    """高欲望 + speak 就绪 → performed。"""
    soul = _FakeSpeakSoul()
    rt = ensure_story_runtime(soul)
    rt.ensure_inbox()
    n = rt.emit_drafts([_draft(desire=0.9)])
    assert n == 1
    beat = rt.ledger.beat(rt.ledger.pending()[0].beat_id) if rt.ledger.pending() else None
    # performed 为终态：pending 为空，从账本任意口径确认非 held
    assert not rt.ledger.held()
    all_states = [rt.ledger.state_of(b.beat_id) for b in [*rt.ledger.pending(), *rt.ledger.held()]]
    assert "held" not in all_states


# ── 用户轮信号（R9 失效判定入口） ──────────────────────────────────────────

def test_signal_sets_director_dirty_on_high_salience():
    rt = ensure_story_runtime(_SoulStub())
    assert not rt.director_dirty
    send_story_signal(_SoulStub(), session_id="live:main",
                      turn_digest="我们真的要搬家了吗？", salience_hint=0.85)
    # 注意：_SoulStub 每次实例不同——runtime 按 soul 实例缓存，需同一实例
    soul = _SoulStub()
    rt2 = ensure_story_runtime(soul)
    send_story_signal(soul, session_id="live:main", turn_digest="嗯", salience_hint=0.2)
    assert not rt2.director_dirty
    assert len(rt2.recent_signals) == 1
    send_story_signal(soul, session_id="live:main", turn_digest="搬家", salience_hint=0.9)
    assert rt2.director_dirty
    rt2.clear_director_dirty()
    assert not rt2.director_dirty


def test_signal_empty_digest_skipped():
    soul = _SoulStub()
    rt = ensure_story_runtime(soul)
    send_story_signal(soul, session_id="live:main", turn_digest="   ")
    assert len(rt.recent_signals) == 0
    send_story_signal(None, session_id="x", turn_digest="soul 缺席静默跳过")  # 不抛错


# ── 剧情卡片（R8 双段结构） ────────────────────────────────────────────────

def test_card_open_freezes_outline_and_advance_syncs():
    synced: list[StoryProgressSync] = []
    store = StoryCardStore(synced.append)

    card = store.open("第一幕：她在矿镇的旧居整理遗物")
    assert card.outline.startswith("第一幕")
    assert card.current == ""

    sync = store.advance(card.card_id, current="整理到一半，发现一封信", upcoming=["读信", "决定回信"])
    assert sync is not None and sync.card_id == card.card_id
    assert len(synced) == 1 and synced[0].current.startswith("整理到一半")
    assert store.get(card.card_id).outline.startswith("第一幕")   # 冻结段不变

    # upcoming 是预告不是承诺：可改写
    store.advance(card.card_id, current="读完信，心绪难平", upcoming=["去邮局"])
    assert synced[-1].upcoming == ("去邮局",)


def test_card_duplicate_open_and_unknown_advance():
    store = StoryCardStore(lambda s: None)
    card = store.open("大纲", card_id="c-fixed")
    try:
        store.open("另一份大纲", card_id="c-fixed")
        assert False, "duplicate open should raise"
    except ValueError:
        pass
    assert store.advance("ghost", current="x") is None
    try:
        store.open("   ")
        assert False, "empty outline should raise"
    except ValueError:
        pass
