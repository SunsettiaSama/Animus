"""landmark → beat 桥单测（R6.2 剧情驱动的第一供给源）。

跑法：cd src && python -m pytest test/soul/storybus/test_landmark_bridge.py -q
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.storybus import BeatDraft  # noqa: E402
from agent.soul.wiring.story import (  # noqa: E402
    beat_from_subjective_event,
    beat_from_surprise,
    beats_from_landmark_fills,
    emit_story_beats,
    ensure_story_runtime,
)


class _SoulStub:
    def __getattr__(self, name):
        raise AttributeError(name)


# ── 草稿构造 ────────────────────────────────────────────────────────────────

def test_beats_from_landmark_fills():
    fills = [
        {"hint": "她整理了旧信件，想起某人", "landmark_id": "lm-1", "salience": 0.7},
        {"narrative": "旧地标完成（无 hint 字段的兼容路径）", "landmark_agenda_id": "ag-2"},
        {"hint": "", "landmark_id": "lm-3"},          # 空叙事跳过
        {},                                            # 空项跳过
    ]
    drafts = beats_from_landmark_fills(fills)
    assert len(drafts) == 2
    assert drafts[0].narrative.startswith("她整理了旧信件")
    assert drafts[0].kind == "landmark_progress"
    assert drafts[0].provenance.landmark_id == "lm-1"
    assert drafts[1].provenance.landmark_id == "ag-2"   # 无 landmark_id 时回退 agenda id
    # 保鲜期默认 6h：不应立即过期
    assert not drafts[0].hint.valid_until == ""
    assert not _expired(drafts[0])


def _expired(item, now: float | None = None) -> bool:
    if isinstance(item, BeatDraft):
        item = item.with_beat_id("t")
    return item.is_expired(now=now)


def test_beat_from_subjective_event():
    assert beat_from_subjective_event({}) is None
    assert beat_from_subjective_event({"hint": "  "}) is None
    d = beat_from_subjective_event({"hint": "她想写一封信"}, source_tick="life-plan-landmark")
    assert d is not None and d.narrative == "她想写一封信"
    assert d.provenance.source_tick == "life-plan-landmark"


def test_beat_from_surprise():
    assert beat_from_surprise({"triggered": False, "narrative": "x"}) is None
    assert beat_from_surprise({"triggered": True, "narrative": ""}) is None
    d = beat_from_surprise({"triggered": True, "narrative": "窗外落了一场急雨", "salience": 0.9})
    assert d is not None and d.kind == "incident"
    assert d.hint.share_desire > 0.5     # 高 salience → 高想说的欲望


# ── 端到端：landmark 事件 → 运行件 → 账本 → 桥 suppressed ─────────────────

def test_emit_story_beats_end_to_end():
    soul = _SoulStub()
    drafts = beats_from_landmark_fills([
        {"hint": "她在黄昏散步时遇到一只猫", "landmark_id": "lm-e2e", "salience": 0.6},
    ])

    emitted = emit_story_beats(soul, drafts)
    assert emitted == 1

    rt = ensure_story_runtime(soul)
    # speak 未就绪（_SoulStub 无 _ensure_speak_service）→ suppressed → held（改期语义）
    held = rt.ledger.held()
    assert len(held) == 1 and held[0].provenance.landmark_id == "lm-e2e"
    assert rt.ledger.state_of(held[0].beat_id) == "held"
    assert not _expired(held[0])


def test_emit_empty_drafts_noop():
    assert emit_story_beats(_SoulStub(), []) == 0
