"""开场白投递去重：state 被清空后同一份开场白不得再推。"""

from __future__ import annotations

import time

from test.soul.speak.test_director_single_character_request import _make_speak_service


def test_same_opening_not_pushed_twice_after_state_wipe(monkeypatch):
    service = _make_speak_service()
    sid = "live:dup-outline"
    sent: list[str] = []
    monkeypatch.setattr(service, "_has_live_stream_session", lambda *_a, **_k: True)
    monkeypatch.setattr(
        service,
        "_execute_outbound_request",
        lambda request, **_k: sent.append(request.ops[0].text) or [],
    )

    service._deliver_narrative_outline(sid, text="灯还亮着。你看见她低着头。")
    service._deliver_narrative_outline(sid, text="灯还亮着。你看见她低着头。")
    assert sent == ["灯还亮着。你看见她低着头。"]

    # 轮转/重置把 director_cache 标记全清掉，memo 仍要拦住同文第二遍
    state = service._state_store.session(sid)
    state.director_cache.pop("narrative_opening", None)
    state.director_cache.pop("narrative_opening_delivered", None)
    service._deliver_narrative_outline(sid, text="灯还亮着。你看见她低着头。")
    assert sent == ["灯还亮着。你看见她低着头。"]

    # 新文本（新章节）放行
    service._deliver_narrative_outline(sid, text="钟摆声停了。她抬起头。")
    assert sent[-1] == "钟摆声停了。她抬起头。"


def test_story_snapshot_restore_keeps_delivered_flag():
    service = _make_speak_service()
    sid = "live:restore-flag"
    state = service._state_store.session(sid)
    live = {
        "plot_arc": {"summary": "修钟", "units": []},
        "opening": "灯还亮着。你看见她低着头。",
        "opening_delivered": True,
        "screenwriter_inited_at": time.time() - 30,
        "counters": {"exchange_count": 2, "turn_index": 1},
    }
    service._apply_story_snapshot(state, live)
    assert state.director_cache["narrative_opening_delivered"] is True
    assert state.director_cache["narrative_opening_ready"] is True
    assert state.director_cache["screenwriter_inited_at"] > 0

    sent: list[str] = []
    monkey_sent = sent
    monkeypatch_service = service
    monkeypatch_service._has_live_stream_session = lambda *_a, **_k: True  # type: ignore[method-assign]
    monkeypatch_service._execute_outbound_request = lambda request, **_k: (  # type: ignore[method-assign]
        monkey_sent.append(request.ops[0].text) or []
    )
    service._maybe_deliver_narrative_opening(sid)
    assert sent == []
