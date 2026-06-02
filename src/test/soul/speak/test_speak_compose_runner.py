from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.orchestrator import SpeakOrchestrator
from agent.soul.speak.orchestrator.runner import SpeakComposeRunner
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue


def _build_composer():
    persona = MagicMock()
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

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
    runner.schedule_prepare(composer, "tao")

    assert runner.take_ready_frame("tao") is None

    deadline = time.time() + 1.0
    frame = None
    while time.time() < deadline:
        frame = runner.take_ready_frame("tao")
        if frame is not None:
            break
        time.sleep(0.01)

    runner.stop()
    assert frame is not None
    assert frame.wants_share is True
    assert "架构" in frame.share_summary
    system = frame.system.render() if hasattr(frame.system, "render") else ""
    _ = system


def test_compose_runner_invalidate_drops_cached_frame():
    composer, _ = _build_composer()
    runner = SpeakComposeRunner()
    runner.start()
    done = threading.Event()

    def _job() -> None:
        frame = composer.prepare("tao")
        runner._frames[("tao", "inbound")] = frame
        done.set()

    runner._worker.enqueue(_job)
    done.wait(timeout=1.0)
    runner.invalidate("tao")
    assert runner.take_ready_frame("tao") is None
    runner.stop()
