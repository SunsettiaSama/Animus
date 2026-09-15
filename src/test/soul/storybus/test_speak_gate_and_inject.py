"""speak 握手门 + 时间轴窗口注入回归（v7 补充，真 SpeakService 装配）。

- ``story_gate_open``：life→speak 握手两硬条件——唤醒 + 激活会话 + 30 分钟
  睡眠（硬编码边界）；
- ``inject_timeline_window``：沿时间轴最近 K 条 + presence 待分享行注入
  compose buffer（真 page_temp/compose 链路，journal 打桩到临时目录）。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent.soul.memory import timeline as tl
from agent.soul.memory.timeline import TurnJournal
from agent.soul.speak.service import SpeakService, _SPEAK_SLEEP_AFTER_SEC


def _speak_service() -> SpeakService:
    bridge = SimpleNamespace(touch_dialogue=lambda *a, **k: None)
    return SpeakService(
        life_outbound=bridge,
        presence=SimpleNamespace(),
        persona=SimpleNamespace(),
    )


def _journal_with_entries(tmp_path):
    journal = TurnJournal(root_dir=str(tmp_path))
    journal.append_turn(session_id="live:main", user_text="在吗", agent_text="在")
    journal.append_event(
        session_id="live:main",
        text="14:00了。给茉莉换了盆",
        kind="story",
        occurred_at="2026-09-15T14:00:00+08:00",
    )
    return journal


# ── 握手门（两个硬条件） ────────────────────────────────────────────────────

def test_gate_requires_wake_and_active_session():
    svc = _speak_service()
    svc._session_manager = SimpleNamespace(has_active_dialogue=lambda sid: True)
    assert svc.story_gate_open() is False          # 从未唤醒：门关

    svc.mark_speak_wake("live:main")
    assert svc.story_gate_open() is True           # 唤醒 + 激活会话：门开

    svc._session_manager = SimpleNamespace(has_active_dialogue=lambda sid: False)
    assert svc.story_gate_open() is False          # 无激活会话：门关（硬条件①）


def test_gate_sleeps_after_30min_hardcoded(monkeypatch):
    svc = _speak_service()
    svc._session_manager = SimpleNamespace(has_active_dialogue=lambda sid: True)
    clock = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    svc.mark_speak_wake("live:main")
    assert svc.story_gate_open() is True
    clock["t"] += _SPEAK_SLEEP_AFTER_SEC - 1       # 睡眠线前 1 秒
    assert svc.story_gate_open() is True
    clock["t"] += 2                                # 越过睡眠线（硬编码 30min）
    assert svc.story_gate_open() is False          # 硬条件②：睡眠即关门

    svc.mark_speak_wake("live:main")               # 唤醒即重开
    assert svc.story_gate_open() is True


# ── 时间轴窗口注入（真 page_temp/compose 链路） ─────────────────────────────

def test_inject_window_with_extra_lines(tmp_path, monkeypatch):
    journal = _journal_with_entries(tmp_path)
    monkeypatch.setattr(tl, "default_journal", lambda: journal)
    svc = _speak_service()
    svc.mark_speak_wake("live:main")

    result = svc.inject_timeline_window(
        "live:main", extra_lines=["她最近想分享：多肉又冒新芽了"]
    )
    assert result.get("ok") is True
    texts = [u.text for u in svc._page_temp.all_units("live:main")]
    assert "用户：在吗" in texts
    assert any("角色：在" in t for t in texts)
    assert any("◐" in t and "茉莉" in t for t in texts)   # 剧情事件带时戳
    assert "她最近想分享：多肉又冒新芽了" in texts          # presence 待分享行


def test_inject_same_page_key_replaces_not_accumulates(tmp_path, monkeypatch):
    journal = _journal_with_entries(tmp_path)
    monkeypatch.setattr(tl, "default_journal", lambda: journal)
    svc = _speak_service()
    svc.mark_speak_wake("live:main")

    svc.inject_timeline_window("live:main")
    svc.inject_timeline_window("live:main")
    texts = [u.text for u in svc._page_temp.all_units("live:main")]
    assert texts.count("用户：在吗") == 1           # 同代替换，不累积


def test_inject_empty_journal_yields_empty_window(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "default_journal", lambda: TurnJournal(root_dir=str(tmp_path)))
    svc = _speak_service()
    svc.mark_speak_wake("live:main")
    result = svc.inject_timeline_window("live:main")
    assert result.get("ok") is True
    assert svc._page_temp.all_units("live:main") == []
