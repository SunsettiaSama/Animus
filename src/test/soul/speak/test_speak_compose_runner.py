from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.orchestrator import SpeakOrchestrator
from agent.soul.speak.orchestrator.runner import SpeakComposeRunner
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill


def _build_composer():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="小A")
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {
        "share_queue": ShareIntentQueue(
            items=[ShareIntent(topic="架构进展", share_desire=ShareDesire.moderate)],
        ).to_dict(),
    }
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.moderate
    snap.interaction.impulse_level = 0.1
    presence.snapshot.return_value = snap
    return SpeakOrchestrator(persona, presence), presence


def test_compose_runner_prefetch_non_blocking():
    composer, _ = _build_composer()
    runner = SpeakComposeRunner()
    runner.start()
    runner.schedule_plan_warm(composer, "tao", target_turn_index=1)
    assert runner.wait_for_plan_ready("tao", 1, timeout_ms=10) is True

    deadline = time.time() + 2.0
    plan = None
    while time.time() < deadline:
        plan = composer.compose_director.load_plan("tao", 1)
        if plan is not None and plan.prepared_frame is not None:
            break
        time.sleep(0.02)

    runner.stop()
    frame = plan.prepared_frame if plan is not None else None
    assert frame is not None
    assert frame.wants_share is True
    assert "架构" in frame.share_summary
    system = frame.system.render() if hasattr(frame.system, "render") else ""
    _ = system


def test_compose_runner_invalidate_drops_cached_frame():
    composer, _ = _build_composer()
    runner = SpeakComposeRunner()
    runner.start()
    runner.schedule_plan_warm(composer, "tao", target_turn_index=1)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        plan = composer.compose_director.load_plan("tao", 1)
        if plan is not None and plan.prepared_frame is not None:
            break
        time.sleep(0.02)
    assert composer.compose_director.load_plan("tao", 1) is not None
    runner.invalidate("tao")
    assert composer.compose_director.load_plan("tao", 1) is None
    runner.stop()
