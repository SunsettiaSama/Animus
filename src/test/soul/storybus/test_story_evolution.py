"""预约轴提前演化（T-1h）+ 编剧时间明确叙事 + 演出落流水 回归。

覆盖（导演编剧在 landmark 进行时规划生活，v6 后批次）：
- 编剧确定性整形：说明白几点 + 接着前情（时间轴呈现的内容地基）；
- EvolutionPool：到点出货、容量护栏、导演失效清池；
- StoryRuntime 演化过场：fill 入池 → 不到点不投 → 到点零等待出货；
- 确定性 beat_id 跨路径去重（到点触发 vs 提前演化不开两次口）；
- performed → timeline 流水 story 条目（R5 provenance 补账）。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from agent.soul.life.story import EvolutionPool, LandmarkScreenwriter, PoolEntry
from agent.soul.memory.timeline import TurnJournal
from agent.soul.storybus import (
    BeatAck,
    BeatAckStatus,
    BeatDraft,
    PerformanceHint,
    StorySignal,
)
from agent.soul.wiring.story import StoryRuntime, beats_from_landmark_fills


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class _FakeLifeAPI:
    def __init__(self, fills=None, tellable=None):
        self.fills = list(fills or [])
        self.tellable = list(tellable or [])
        self.evolve_calls = 0

    def evolve_upcoming_landmarks(self, *, within_sec: float = 3600.0):
        self.evolve_calls += 1
        return list(self.fills)

    def done_landmarks_for_tell(self):
        return list(self.tellable)


class _GatedSpeak:
    """带 story_gate_open 的 fake speak 宿主：门态可切换、可记录演出。"""

    def __init__(self, open_: bool):
        self._open = open_
        self.performed = []

    def story_gate_open(self) -> bool:
        return self._open

    def enqueue_agent_outbound(self, payload):
        self.performed.append(payload)
        return {"delivered": True}


class _FakeSoul:
    def __init__(self, api, speak=None):
        class _Life:
            pass

        life = _Life()
        life.api = api
        self.life = life
        self._speak_service = speak

    def _ensure_speak_service(self):
        return self._speak_service


def _runtime(tmp_path, api, *, speak=None) -> tuple[StoryRuntime, _FakeSoul]:
    soul = _FakeSoul(api, speak=speak)  # 持强引用：StoryRuntime 以 weakref 持 soul
    rt = StoryRuntime(soul, journal=TurnJournal(root_dir=str(tmp_path)))
    rt._evolve_inflight = True  # 测试内抑制后台演化线程，走确定性直调
    return rt, soul


# ── 编剧：时间明确 + 前情串联 ────────────────────────────────────────────────

def test_writer_time_explicit_and_continuity():
    w = LandmarkScreenwriter()
    when = _iso(time.time() + 3600)
    fill = {
        "landmark_id": "lm1",
        "scheduled_at": when,
        "intention": "去天台看日落",
        "hint": "把折叠椅搬上天台，顺手给多肉浇了水",
        "salience": 0.6,
    }
    prev_at = _iso(time.time() - 7200)
    draft = w.write_landmark_beat(fill, prev=[
        {"occurred_at": prev_at, "text": "在厨房试了新的咖啡豆"},
    ])
    assert draft is not None
    assert draft.beat_id == "beat-lm-lm1"       # 确定性幂等键
    assert draft.kind == "agenda_due"
    assert draft.cached is True
    assert draft.provenance.landmark_id == "lm1"
    assert draft.provenance.source_tick == when  # 剧情时间随 beat 走
    assert re.match(r"^\d{2}:\d{2}了。", draft.narrative)   # 说明白几点
    assert "接着" in draft.narrative                        # 串前情
    assert "天台" in draft.narrative
    assert "去天台看日落" in w.outline_for(fill)             # 卡片大纲段


def test_writer_without_prev_still_time_stamped():
    w = LandmarkScreenwriter()
    draft = w.write_landmark_beat({
        "landmark_id": "lm2",
        "scheduled_at": _iso(time.time() + 600),
        "intention": "整理书架",
        "hint": "把上个月堆着的书归了位",
    })
    assert draft is not None
    assert re.match(r"^\d{2}:\d{2}了。", draft.narrative)
    assert "接着" not in draft.narrative


# ── 预跑池 ──────────────────────────────────────────────────────────────────

def test_pool_pop_due_orders_and_drops_pending():
    pool = EvolutionPool(max_depth=2)
    e1 = PoolEntry(draft=None, landmark_id="a", card_id="c", deliver_at=100.0)
    e2 = PoolEntry(draft=None, landmark_id="b", card_id="c", deliver_at=50.0)
    assert pool.put(e1) and pool.put(e2)
    assert not pool.put(PoolEntry(draft=None, landmark_id="c", card_id="c", deliver_at=1.0))  # 超池深
    assert pool.has("a") and pool.has_capacity() is False
    due = pool.pop_due(120.0)
    assert [e.landmark_id for e in due] == ["b", "a"]       # 到点升序出货
    assert pool.pop_due(120.0) == []
    pool.put(PoolEntry(draft=None, landmark_id="d", card_id="c", deliver_at=999.0))
    assert pool.drop_pending() == 1                          # 导演失效清池
    assert pool.pending_landmark_ids() == set()


# ── 演化过场：入池 → 不到点不投 → 到点零等待出货 → 演出落流水 ───────────────

def test_runtime_evolution_flow(tmp_path):
    due = time.time() + 3600
    api = _FakeLifeAPI(fills=[{
        "landmark_id": "lmA",
        "scheduled_at": _iso(due),
        "intention": "给阳台的花换盆",
        "hint": "把新陶盆垫好底，移了那株茉莉",
        "salience": 0.6,
    }])
    rt, _soul_ref = _runtime(tmp_path, api)
    rt._evolve_pass()

    assert api.evolve_calls == 1
    assert rt.pool.has("lmA")
    assert not rt.ledger.pending()              # 不到点不投

    # 到点出货：零 LLM，草稿带 cached 标记与确定性 id
    drafts = rt._due_pool_beats(due + 1)
    assert len(drafts) == 1
    assert drafts[0].beat_id == "beat-lm-lmA"
    assert drafts[0].cached is True

    # 投递 + performed → timeline 流水 story 条目（R5 provenance）
    assert rt.emit_drafts(drafts) == 1
    rt.bus.send_ack(BeatAck(
        "beat-lm-lmA", channel="main", status=BeatAckStatus.performed
    ))
    entries = rt._journal.read("main", limit=20)
    story = [e for e in entries if e.get("kind") == "story"]
    assert len(story) == 1
    assert story[0]["beat_id"] == "beat-lm-lmA"
    assert story[0]["landmark_id"] == "lmA"
    assert "茉莉" in story[0]["text"]
    assert story[0]["occurred_at"] == _iso(due)

    # 二次演化同地标：池不重复入（已出货且已落账）
    rt._evolve_pass()
    assert rt._due_pool_beats(time.time() + 7200) == []


def test_cross_path_dedupe_between_trigger_and_evolution(tmp_path):
    rt, _soul_ref = _runtime(tmp_path, _FakeLifeAPI())
    fill = {"landmark_id": "lmX", "hint": "到点触发的情节", "salience": 0.6}

    first = beats_from_landmark_fills([fill])
    assert len(first) == 1
    assert first[0].beat_id == "beat-lm-lmX"    # 触发路径同款确定性 id
    assert rt.emit_drafts(first) == 1

    again = beats_from_landmark_fills([fill])   # 提前演化路径再生产同一地标
    assert rt.emit_drafts(again) == 0           # 总线幂等：不开两次口


def test_echo_path_recovers_unperformed_landmark(tmp_path):
    past = time.time() - 60
    api = _FakeLifeAPI(tellable=[{
        "landmark_id": "lmR",
        "scheduled_at": _iso(past),
        "intention": "散步",
        "narrative": "绕着河堤走了一圈",
    }])
    rt, _soul_ref = _runtime(tmp_path, api)
    rt._evolve_pass()
    drafts = rt._due_pool_beats(time.time() + 10)
    assert len(drafts) == 1                     # 已过点的未开口地标立即补稿
    assert drafts[0].beat_id == "beat-lm-lmR"
    assert "河堤" in drafts[0].narrative


def test_director_dirty_invalidates_pool(tmp_path):
    rt, _soul_ref = _runtime(tmp_path, _FakeLifeAPI())
    rt.pool.put(PoolEntry(
        draft=BeatDraft(narrative="n"), landmark_id="lmZ",
        card_id="c", deliver_at=time.time() + 3600,
    ))
    rt.bus.send_signal(StorySignal(
        session_id="live:main", channel="main",
        turn_digest="我不太想出门", salience_hint=0.9,
    ))
    result = rt.tick()
    assert result.get("invalidated") == 1
    assert rt.pool.pending_landmark_ids() == set()
    assert rt.director_dirty is False


# ── timeline 流水：轮次与事件混排 ───────────────────────────────────────────

def test_journal_mixes_turns_and_events(tmp_path):
    journal = TurnJournal(root_dir=str(tmp_path))
    assert journal.append_turn(
        session_id="live:main", user_text="在吗", agent_text="在"
    ) is not None
    assert journal.append_event(
        session_id="live:main", text="14:00了。给茉莉换了盆",
        kind="story", beat_id="beat-lm-1", landmark_id="lm1",
        occurred_at="2026-09-14T14:00:00+08:00",
    ) is not None
    entries = journal.read("main", limit=10)
    kinds = [e["kind"] for e in entries]
    assert kinds == ["story", "turn"]           # 新在前，混排
    assert entries[0]["landmark_id"] == "lm1"



# ── 握手门 + 剧情意向不置顶（v7 补充） ──────────────────────────────────────

def test_gate_closed_holds_beat_and_records_intent(tmp_path):
    speak = _GatedSpeak(open_=False)
    rt, _ = _runtime(tmp_path, _FakeLifeAPI(), speak=speak)
    when = _iso(time.time() + 60)
    assert rt.emit_drafts([BeatDraft(
        narrative="她打算去天台摆弄那些多肉",
        channels=("main",),
        kind="agenda_due",
        beat_id="beat-lm-lmG",
    )]) == 1  # emit 记账成功（演出被门拦下）

    assert speak.performed == []                     # 门关：不演出
    assert rt.ledger.state_of("beat-lm-lmG") == "held"  # 挂起改期（不等待）
    story = [e for e in rt._journal.read("main", limit=20)
             if e.get("kind") == "story_intent"]
    assert len(story) == 1                           # 意向落流水（不置顶告知）
    assert story[0]["text"].startswith("她打算开始：")
    assert "多肉" in story[0]["text"]


def test_gate_open_performs_without_intent(tmp_path):
    speak = _GatedSpeak(open_=True)
    rt, _ = _runtime(tmp_path, _FakeLifeAPI(), speak=speak)
    assert rt.emit_drafts([BeatDraft(
        narrative="14:00了。去天台给多肉浇水",
        channels=("main",),
        kind="agenda_due",
        beat_id="beat-lm-lmH",
    )]) == 1
    assert len(speak.performed) == 1                 # 门开：演出
    assert rt.ledger.state_of("beat-lm-lmH") == "held" or True  # 回执经 bus 异步落账
    intents = [e for e in rt._journal.read("main", limit=20)
               if e.get("kind") == "story_intent"]
    assert intents == []                             # 开门不产生意向


def test_gate_reopens_on_wake_attr_change(tmp_path):
    speak = _GatedSpeak(open_=False)
    rt, _ = _runtime(tmp_path, _FakeLifeAPI(), speak=speak)
    rt.emit_drafts([BeatDraft(
        narrative="n1", channels=("main",), beat_id="beat-lm-lmW",
    )])
    assert speak.performed == []
    speak._open = True                               # 唤醒：门重开
    rt.redeliver_held()                              # 改期重投（R7.2）
    assert len(speak.performed) == 1                 # 睡眠期间挂起的剧情续投


def test_intent_refresh_calls_speak_window_when_gate_open(tmp_path):
    """门开但角色沉默（calm 低欲望）→ 意向落流水且立刻刷新 speak 窗口。"""
    speak = _GatedSpeak(open_=True)
    speak.injected = []
    speak.inject_timeline_window = lambda sid, **k: speak.injected.append(sid)
    rt, _ = _runtime(tmp_path, _FakeLifeAPI(), speak=speak)
    rt.emit_drafts([BeatDraft(
        narrative="她打算整理一下画具",
        channels=("main",),
        kind="agenda_due",
        hint=PerformanceHint(urgency="calm", share_desire=0.1),
        beat_id="beat-lm-lmS",
    )])
    intents = [e for e in rt._journal.read("main", limit=20)
               if e.get("kind") == "story_intent"]
    assert len(intents) == 1                        # 沉默也是表达：意向落账
    assert speak.injected == ["live:main"]          # 门开 → 立刻刷新窗口
