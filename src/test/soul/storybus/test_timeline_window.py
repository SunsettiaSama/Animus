"""时间轴窗口上下文（上下文唯一历史语义，v7）回归。

- ``recent_window``：最近 k 条（轮次/事件混排），旧 → 新；
- ``format_window_lines``：条目 → 上下文行（用户：/角色：/带时戳的剧情事件）。
"""
from __future__ import annotations

from agent.soul.memory.timeline import TurnJournal, format_window_lines


def _journal(tmp_path):
    return TurnJournal(root_dir=str(tmp_path))


def test_recent_window_returns_oldest_first_mixed(tmp_path):
    j = _journal(tmp_path)
    for i in range(5):
        j.append_turn(session_id="live:main", user_text=f"u{i}", agent_text=f"a{i}")
    j.append_event(session_id="live:main", text="14:00了。给茉莉换了盆", kind="story")
    window = j.recent_window("main", k=3)
    # 新在前读出后反转：旧 → 新，最新的是 story 事件
    assert window[-1]["kind"] == "story"
    assert window[0]["user_text"] == "u3"
    assert len(window) == 3


def test_recent_window_empty_channel(tmp_path):
    assert _journal(tmp_path).recent_window("ghost", k=5) == []


def test_format_window_lines_mixed_kinds():
    entries = [
        {"kind": "turn", "user_text": "在吗", "agent_text": "在",
         "at": "2026-09-14T06:00:00+00:00"},
        {"kind": "story", "text": "给茉莉换了盆",
         "at": "2026-09-14T06:05:00+00:00",
         "occurred_at": "2026-09-14T06:00:00+00:00"},
        {"kind": "turn", "user_text": "", "agent_text": "刚忙完"},
    ]
    lines = format_window_lines(entries)
    assert lines[0] == "用户：在吗"
    assert lines[1] == "角色：在"
    assert lines[2].startswith("[")           # 剧情事件带剧情时戳
    assert "◐" in lines[2] and "茉莉" in lines[2]
    assert lines[3] == "角色：刚忙完"          # 空用户文本不产生空行


def test_format_window_lines_story_without_timestamp():
    lines = format_window_lines([
        {"kind": "story", "text": "x", "at": "", "occurred_at": ""},
    ])
    assert lines == ["◐ x"]


# ── 1k 条分段（v7 补充：缓存文件化，前端与 speak 同源） ──────────────────────

def test_segment_rolls_at_limit(tmp_path):
    j = TurnJournal(root_dir=str(tmp_path), segment_max=3)
    for i in range(5):
        j.append_turn(session_id="live:main", user_text=f"u{i}", agent_text=f"a{i}")
    files = sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".jsonl"))
    assert files == ["main.0001.jsonl", "main.0002.jsonl"]
    window = j.recent_window("main", k=10)
    assert [e["user_text"] for e in window] == ["u0", "u1", "u2", "u3", "u4"]


def test_legacy_single_file_still_readable(tmp_path):
    legacy = tmp_path / "main.jsonl"
    legacy.write_text(
        '{"kind": "turn", "at": "2026-09-14T06:00:00+00:00", "channel": "main",'
        ' "user_text": "旧文件里的轮次", "agent_text": "旧回答"}\n',
        encoding="utf-8",
    )
    j = TurnJournal(root_dir=str(tmp_path), segment_max=10)
    j.append_turn(session_id="live:main", user_text="新段轮次", agent_text="")
    entries = j.recent_window("main", k=10)
    assert entries[0]["user_text"] == "旧文件里的轮次"   # 窗口旧 → 新
    assert entries[-1]["user_text"] == "新段轮次"        # 新写入进新段


def test_cross_segment_before_pagination(tmp_path):
    """分页游标跨段有效（timeline API 分页在分段文件上不断页）。"""
    import time as _time

    j = TurnJournal(root_dir=str(tmp_path), segment_max=3)
    for i in range(5):
        j.append_turn(session_id="live:main", user_text=f"u{i}", agent_text=f"a{i}")
        _time.sleep(0.02)  # 游标按 at 严格小于过滤：保证时间戳可分辨
    page1 = j.read("main", limit=2)                     # 新在前：u4, u3
    assert [e["user_text"] for e in page1] == ["u4", "u3"]
    cursor = page1[-1]["at"]
    page2 = j.read("main", limit=2, before=cursor)      # 跨段：u2, u1
    assert [e["user_text"] for e in page2] == ["u2", "u1"]
    page3 = j.read("main", limit=2, before=page2[-1]["at"])
    assert [e["user_text"] for e in page3] == ["u0"]
    assert j.read("main", limit=2, before=page3[-1]["at"]) == []
