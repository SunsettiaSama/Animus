"""心跳存活测试：唤起线任何组件故障不允许线程死亡或静默（F1–F5 修复验收）。

与 test_heartbeat_integration.py（真 SoulService、分钟级）互补：本文件
全部用假件，秒级，专测"故障之下线程/读口的存活"。
"""

from __future__ import annotations

import os
import time
from datetime import time as dtime
from types import SimpleNamespace

import pytest

from agent.soul.heartbeat.config import SoulHeartbeatConfig
from agent.soul.heartbeat.runtime.core_service import HeartbeatCoreService
from agent.soul.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult
from agent.soul.heartbeat.window import within_window
from agent.soul.heartbeat.orchestrate.worker import SoulEvolutionWorker


# ── 假件 ─────────────────────────────────────────────────────────────────────

class _BoomHeartbeat:
    """tick 必炸（模拟 soul 侧 handler 故障）。"""

    def __init__(self, cfg: SoulHeartbeatConfig) -> None:
        self._cfg = cfg
        self._soul = None

    def tick(self):
        raise RuntimeError("tick 炸了（模拟 soul 侧异常）")


class _OkHeartbeat:
    def __init__(self, cfg: SoulHeartbeatConfig) -> None:
        self._cfg = cfg
        self._soul = None

    def tick(self):
        return HeartbeatTickResult(outcome="ok", reason="test", detail_for_inject="待注入摘要")


class _FakeLLMService:
    def __init__(self, llm) -> None:
        self._llm = llm

    def get_aux_llm(self, name):
        return self._llm


class _BoomLLM:
    def generate_messages(self, messages):
        raise RuntimeError("LLM 连接失败")


class _SlowLLM:
    def generate_messages(self, messages):
        time.sleep(5.0)
        return "INJECT"


class _ReplyLLM:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def generate_messages(self, messages):
        return self._reply


class _BoomOrchestrator:
    def __init__(self) -> None:
        self.executed = 0

    def execute_item(self, item):
        self.executed += 1
        raise RuntimeError("dispatch 炸了")


def _always_open_cfg(**overrides) -> SoulHeartbeatConfig:
    base = dict(
        poll_interval_sec=5,
        active_hours_start="",
        active_hours_end="",
    )
    base.update(overrides)
    return SoulHeartbeatConfig(**base)


# ── F1：core 线程兜异常 ──────────────────────────────────────────────────────

def test_safe_iteration_swallows_tick_exception_and_counts():
    core = HeartbeatCoreService(
        _BoomHeartbeat(_always_open_cfg()), register_global_mailbox=False
    )
    assert core._safe_iteration() is False
    assert core._safe_iteration() is False
    assert core.consecutive_failures == 2


def test_core_thread_survives_tick_exception():
    core = HeartbeatCoreService(
        _BoomHeartbeat(_always_open_cfg()), register_global_mailbox=False
    )
    core.start()
    time.sleep(8)  # 覆盖至少一个 5s 轮询周期
    try:
        assert core._thread is not None and core._thread.is_alive()
        assert core.consecutive_failures >= 1
    finally:
        core.stop()


# ── F1b：演化 worker 兜异常 + pending 释放 ───────────────────────────────────

def test_worker_run_one_swallows_exception_and_releases_pending():
    worker = SoulEvolutionWorker(_BoomOrchestrator())
    item = SimpleNamespace(id="memory-wander", domain="memory", action="wander")
    worker._run_one(item)  # 不抛
    assert worker._orchestrator.executed == 1
    assert worker.enqueue(item) is True  # pending 已释放，可再次入队


def test_worker_thread_survives_item_exception():
    worker = SoulEvolutionWorker(_BoomOrchestrator())
    worker.start()
    worker.enqueue(SimpleNamespace(id="memory-wander", domain="memory", action="wander"))
    time.sleep(1.5)  # _WAKE_POLL_SEC=0.5，确保任务被消费且异常被兜住
    try:
        assert worker._thread is not None and worker._thread.is_alive()
        again = SimpleNamespace(id="memory-wander", domain="memory", action="wander")
        assert worker.enqueue(again) is True  # pending 已释放
    finally:
        worker.stop()


# ── F2：窗口判定（跨零点 + 坏配置 fail-open） ───────────────────────────────

@pytest.mark.parametrize("start,end,now,expected", [
    ("22:00", "06:00", dtime(23, 0), True),
    ("22:00", "06:00", dtime(3, 0), True),
    ("22:00", "06:00", dtime(12, 0), False),
    ("08:00", "22:00", dtime(12, 0), True),
    ("08:00", "22:00", dtime(23, 30), False),
    ("08:00", "22:00", dtime(8, 0), True),
])
def test_within_window_inclusive_and_cross_midnight(start, end, now, expected):
    assert within_window(start, end, "Asia/Shanghai", now=now) is expected


def test_within_window_bad_config_fails_open():
    assert within_window("08:00", "22:00", "Mars/Olympus") is True
    assert within_window("not-a-time", "22:00", "Asia/Shanghai") is True
    assert within_window("", "", "") is True


# ── F3：tick_log 轮转 + 坏行容错 ─────────────────────────────────────────────

def test_tick_log_rotates_on_size(tmp_path):
    log = HeartbeatTickLog(str(tmp_path), max_bytes=400)
    for i in range(10):
        log.append(HeartbeatTickResult(outcome="ok", reason=f"r{i}", duration_ms=1))
    assert os.path.exists(log._rotated_path)
    assert log.recent(50)  # 轮转后的当前代仍有内容


def test_tick_log_recent_tolerates_corrupt_line(tmp_path):
    log = HeartbeatTickLog(str(tmp_path))
    log.append(HeartbeatTickResult(outcome="ok", reason="good-1"))
    with open(log._path, "a", encoding="utf-8") as f:
        f.write("{截断的坏行\n")
    log.append(HeartbeatTickResult(outcome="ok", reason="good-2"))
    entries = log.recent(10)
    reasons = [e["reason"] for e in entries]
    assert reasons == ["good-2", "good-1"]  # 坏行被跳过，好行按新→旧返回


# ── F4：注入判定 LLM 超时/异常 → DEFER ─────────────────────────────────────

def _agent_mode_core(llm, *, timeout: float = 0.2) -> HeartbeatCoreService:
    return HeartbeatCoreService(
        _OkHeartbeat(_always_open_cfg(
            inject_window_mode="agent",
            inject_judge_timeout_sec=timeout,
        )),
        llm_service=_FakeLLMService(llm),
        register_global_mailbox=False,
    )


def test_inject_judge_llm_exception_defers_without_raising():
    assert _agent_mode_core(_BoomLLM())._agent_accepts_inject("待注入摘要") is False


def test_inject_judge_llm_timeout_defers_quickly():
    t0 = time.monotonic()
    assert _agent_mode_core(_SlowLLM())._agent_accepts_inject("待注入摘要") is False
    assert time.monotonic() - t0 < 3.0  # 0.2s 超时生效，不被 5s 慢调用拖住


def test_inject_judge_reply_parsing():
    assert _agent_mode_core(_ReplyLLM("INJECT"))._agent_accepts_inject("x") is True
    assert _agent_mode_core(_ReplyLLM("DEFER"))._agent_accepts_inject("x") is False
    assert _agent_mode_core(_ReplyLLM(""))._agent_accepts_inject("x") is False


def test_agent_mode_iteration_survives_judge_failure_and_keeps_deferred():
    core = _agent_mode_core(_BoomLLM())
    core._iteration()  # 判定炸了也不允许抛出
    assert core.mailbox.take_for_prompt() is None  # 未注入
    with core._deferred_lock:
        assert core._deferred == "待注入摘要"       # pending 保留，下轮重试
