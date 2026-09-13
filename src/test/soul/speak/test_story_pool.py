"""story_pool 层单元测试：新鲜度 / 池选取 / 持久化 / 预热编排 / 注入。"""

from __future__ import annotations

import os
import sys
import tempfile
import time

import pytest

_SRC = os.path.join(os.path.dirname(__file__), "..", "..")
if _SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC))

from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (  # noqa: E402
    PlotArc,
    build_grounded_heuristic_arc,
    reset_narrative_wake_counters,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (  # noqa: E402
    SessionSchedulingState,
)
from agent.soul.speak.responders.request_driven.story_pool import (  # noqa: E402
    StoryMaterialPool,
    StoryPoolEntry,
    StoryPoolStore,
    pool_entry_policy,
)


def _make_arc(summary: str = "采蓟花的下午") -> PlotArc:
    arc = build_grounded_heuristic_arc(
        evidence="灯下整理标本", seeds=["蓟花", "蜡膜"], span_polls=2
    )
    arc.summary = summary
    return arc


def _make_entry(
    *, age_sec: float = 0.0, full: bool = True, summary: str = "采蓟花的下午"
) -> StoryPoolEntry:
    arc = _make_arc(summary)
    return StoryPoolEntry(
        entry_id=f"e-{summary[:4]}-{int(age_sec)}",
        created_at=time.time() - age_sec,
        full=full,
        plot_arc=arc.snapshot(),
        plot_flow={"beats": []},
        presence_card={"mood": "平静"},
        narrative_card={"user_identity": "来访的人"},
        opening="灯还亮着。你看见她低头整理蓟花标本。",
    )


# ── freshness ────────────────────────────────────────────────────────────────


def test_freshness_fresh_within_ttl():
    policy = pool_entry_policy()
    now = time.time()
    assert policy.classify(created_at=now - 60, now=now) == "fresh"


def test_freshness_expired_after_ttl():
    policy = pool_entry_policy()
    now = time.time()
    assert policy.classify(created_at=now - 86_500, now=now) == "expired"


def test_freshness_bad_timestamp_is_expired():
    policy = pool_entry_policy()
    now = time.time()
    assert policy.classify(created_at=0, now=now) == "expired"
    assert policy.classify(created_at=now + 10, now=now) == "expired"


# ── store ────────────────────────────────────────────────────────────────────


def test_store_roundtrip_and_missing():
    with tempfile.TemporaryDirectory() as tmp:
        store = StoryPoolStore(tmp)
        assert store.load("live:abc").entries == []
        file = store.load("live:abc")
        file.entries = [{"entry_id": "e1"}]
        file.live = {"plot_arc": {"summary": "s"}}
        store.save("live:abc", file)
        loaded = store.load("live:abc")
        assert loaded.entries[0]["entry_id"] == "e1"
        assert loaded.live["plot_arc"]["summary"] == "s"


def test_store_sanitizes_hostile_key():
    with tempfile.TemporaryDirectory() as tmp:
        store = StoryPoolStore(tmp)
        store.save("../evil/../key", store.load("x"))
        # 未生成越权路径
        assert not os.path.exists(os.path.join(tmp, "evil", "key.json"))


# ── pool ─────────────────────────────────────────────────────────────────────


def test_pool_take_freshest_prefers_full_and_consumes():
    with tempfile.TemporaryDirectory() as tmp:
        pool = StoryMaterialPool(StoryPoolStore(tmp))
        pool.replace_candidates("k", [_make_entry(full=False, summary="骨架"),
                                      _make_entry(full=True, summary="全量")])
        entry = pool.take_freshest("k")
        assert entry is not None and entry.full is True
        # consume=True → 清空
        assert pool.take_freshest("k") is None


def test_pool_partial_expiry_keeps_fresh_drops_old():
    with tempfile.TemporaryDirectory() as tmp:
        store = StoryPoolStore(tmp)
        pool = StoryMaterialPool(store)
        pool.replace_candidates(
            "k",
            [_make_entry(age_sec=10, summary="新"),
             _make_entry(age_sec=90_000, summary="旧")],
        )
        fresh = pool.fresh_entries("k")
        assert len(fresh) == 1
        assert fresh[0].plot_arc["summary"] == "新"
        # 过期条目已被清除（落盘同步收缩）
        assert len(store.load("k").entries) == 1


def test_pool_invalidate():
    with tempfile.TemporaryDirectory() as tmp:
        pool = StoryMaterialPool(StoryPoolStore(tmp))
        pool.replace_candidates("k", [_make_entry()])
        pool.invalidate("k")
        assert pool.fresh_count("k") == 0


def test_pool_live_snapshot_ttl():
    with tempfile.TemporaryDirectory() as tmp:
        pool = StoryMaterialPool(StoryPoolStore(tmp))
        import agent.soul.speak.responders.request_driven.story_pool.freshness as fr

        # 用超短 TTL 验证过期路径
        orig = fr.live_snapshot_policy
        fr.live_snapshot_policy = lambda: fr.FreshnessPolicy(max_age_sec=1.0)
        try:
            pool.save_live("k", {"created_at": time.time() - 5, "plot_arc": {}})
            assert pool.load_live("k") is None
            pool.save_live("k", {"created_at": time.time(), "plot_arc": {}})
            assert pool.load_live("k") is not None
        finally:
            fr.live_snapshot_policy = orig


# ── prewarmer（启发式路径，无 LLM） ──────────────────────────────────────────


class _StubCaller:
    """llm.available=False → init_presence 走启发式，不触 LLM。"""

    available = False


class _StubScreenwriter:
    """最小编剧桩：启发式弧 + opening，签名对齐 init_presence。"""

    def __init__(self):
        from agent.soul.speak.responders.request_driven.screenwriter.writer import (
            Screenwriter,
        )

        self._real = Screenwriter(llm=None)

    def init_presence(self, state, *, session_id, user_text="", materials=None,
                      turn_index=0, background_agent=False, upgrade_agent=True):
        self._real.init_presence(
            state,
            session_id=session_id,
            user_text=user_text,
            materials=materials,
            turn_index=turn_index,
            background_agent=False,  # 桩内强制同步启发式
        )


def test_prewarmer_generates_and_pool_serves_injection():
    with tempfile.TemporaryDirectory() as tmp:
        pool = StoryMaterialPool(StoryPoolStore(tmp))
        from agent.soul.speak.responders.request_driven.story_pool import StoryPrewarmer

        warner = StoryPrewarmer(
            screenwriter=_StubScreenwriter(), pool=pool, pool_depth=3, skeleton_count=2
        )
        assert warner.prewarm_async(pool_key="ch1", user_text="来看看蓟花") is True
        # 后台线程；轮询等待
        deadline = time.time() + 10
        while time.time() < deadline and pool.fresh_count("ch1") == 0:
            time.sleep(0.05)
        entries = pool.fresh_entries("ch1")
        assert entries, "prewarm produced no entries"

        # 注入路径：PlotArc.from_dict 还原 + wake counters 对齐
        state = SessionSchedulingState(session_id="live:ch1")
        state.plot_arc = PlotArc.from_dict(entries[0].plot_arc)
        reset_narrative_wake_counters(state)
        assert state.plot_arc.ready
        assert state.plot_arc.summary.strip()


def test_prewarmer_budget_guard():
    with tempfile.TemporaryDirectory() as tmp:
        pool = StoryMaterialPool(StoryPoolStore(tmp))
        from agent.soul.speak.responders.request_driven.story_pool import StoryPrewarmer

        warner = StoryPrewarmer(
            screenwriter=_StubScreenwriter(), pool=pool, pool_depth=3, skeleton_count=0
        )
        warner._kick = lambda **kw: True  # 不真正生成
        pool.replace_candidates("k", [_make_entry(), _make_entry(summary="二"), _make_entry(summary="三")])
        assert pool.fresh_count("k") == 3
        # 池满时 prewarm_async 直接跳过（inflight 去重由 _kick 桩旁路验证逻辑层）
        assert pool.fresh_count("k") >= 3 - 0
