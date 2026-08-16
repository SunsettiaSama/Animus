from __future__ import annotations

import random

from agent.soul.speak.responders.request_driven.orchestrator.state.core.poll import (
    DEFAULT_LADDER_SEC,
    PollFrameManager,
)


def test_ladder_first_three_nominals():
    assert DEFAULT_LADDER_SEC[:3] == (5.0, 15.0, 30.0)


def test_schedule_ladder_advances_5_15_30():
    frame_mgr = PollFrameManager(session_id="s", _rng=random.Random(0), jitter_ratio=0.0)
    frame_mgr.reset_decay()
    frame_mgr.schedule_next()  # first after user → ~5s
    assert frame_mgr.ladder_step == 0
    assert abs(frame_mgr.last_t_sec - 5.0) < 1e-9
    frame_mgr.schedule_next()  # → ~15s
    assert frame_mgr.ladder_step == 1
    assert abs(frame_mgr.last_t_sec - 15.0) < 1e-9
    frame_mgr.schedule_next()  # → ~30s
    assert frame_mgr.ladder_step == 2
    assert abs(frame_mgr.last_t_sec - 30.0) < 1e-9


def test_sample_t_jitter_stays_near_nominal():
    frame_mgr = PollFrameManager(
        session_id="s",
        _rng=random.Random(1),
        jitter_ratio=0.2,
        min_t_sec=1.0,
    )
    frame_mgr.ladder_step = 1  # nominal 15
    samples = [frame_mgr.sample_t() for _ in range(80)]
    assert min(samples) >= 15.0 * 0.8 - 1e-9
    assert max(samples) <= 15.0 * 1.2 + 1e-9


def test_p_fire_decreases_with_ladder_step():
    frame_mgr = PollFrameManager(session_id="s", p_floor=0.12)
    frame_mgr.ladder_step = 0
    p0 = frame_mgr.p_fire()
    frame_mgr.ladder_step = 2
    p2 = frame_mgr.p_fire()
    frame_mgr.ladder_step = 5
    p5 = frame_mgr.p_fire()
    assert p0 > p2 >= p5
    assert p0 > 0.95
    assert p5 == max(0.12, 1.0 - 0.12 * 5)


def test_take_due_frame_skip_keeps_same_rung():
    frame_mgr = PollFrameManager(
        session_id="s",
        _rng=random.Random(2),
        jitter_ratio=0.0,
    )
    frame_mgr.schedule_next()
    step_before = frame_mgr.ladder_step
    frame_mgr._rng.random = lambda: 1.0  # type: ignore[method-assign]
    decision = frame_mgr.take_due_frame(now=frame_mgr.next_fire_at + 0.01)
    assert decision.skipped
    assert frame_mgr.armed
    assert frame_mgr.ladder_step == step_before


def test_take_due_frame_fire_disarms():
    frame_mgr = PollFrameManager(
        session_id="s",
        _rng=random.Random(3),
        p_floor=1.0,
        jitter_ratio=0.0,
    )
    frame_mgr.schedule_next()
    decision = frame_mgr.take_due_frame(now=frame_mgr.next_fire_at + 0.01)
    assert decision.execute
    assert not decision.skipped
    assert not frame_mgr.armed
    assert frame_mgr.next_fire_at == 0.0


def test_reset_decay_restarts_ladder():
    frame_mgr = PollFrameManager(session_id="s", _rng=random.Random(4), jitter_ratio=0.0)
    frame_mgr.schedule_next()
    frame_mgr.schedule_next()
    assert frame_mgr.ladder_step == 1
    frame_mgr.reset_decay()
    assert frame_mgr.ladder_step == 0
    assert frame_mgr._first_schedule is True
    assert frame_mgr.next_fire_at == 0.0
    frame_mgr.schedule_next()
    assert abs(frame_mgr.last_t_sec - 5.0) < 1e-9
