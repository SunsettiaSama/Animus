"""reset 异步 close 不得踢掉已重连的生命线。"""

from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.orchestrator.runtime.orchestrator_thread import (
    OrchestratorThread,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    StateStore,
)


def test_async_close_does_not_drop_reactivated_session() -> None:
    store = StateStore()
    thread = OrchestratorThread(state_store=store)
    thread.start()
    sid = "life-line-race"

    epoch1 = thread.activate_session(sid)
    assert epoch1 == 1
    assert sid in thread._active_sessions
    store.session(sid).notes.append("seed-v1")

    # 模拟 reset：同步 deactivate + 异步 close（旧代数）
    thread.notify_session_close(sid)
    assert sid not in thread._active_sessions

    # 重连：新一代 activate + 写入状态
    epoch2 = thread.activate_session(sid)
    assert epoch2 == 2
    store.session(sid).notes.append("seed-v2")

    # 等待过期 close 跑完
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if thread.session_epoch(sid) == 2 and sid in thread._active_sessions:
            # 给 worker 一点时间执行已入队的 close
            time.sleep(0.05)
            break
        time.sleep(0.01)

    assert thread.session_epoch(sid) == 2
    assert sid in thread._active_sessions
    assert "seed-v2" in store.session(sid).notes

    thread.stop()


def test_matching_epoch_close_clears_inactive_session() -> None:
    store = StateStore()
    thread = OrchestratorThread(state_store=store)
    thread.start()
    sid = "life-line-close"

    thread.activate_session(sid)
    store.session(sid).notes.append("gone")
    thread.notify_session_close(sid)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if sid not in thread._active_sessions and not store.session(sid).notes:
            break
        time.sleep(0.01)

    assert sid not in thread._active_sessions
    # clear_session 会换新空态；notes 应被清掉
    assert store.session(sid).notes == []

    thread.stop()
