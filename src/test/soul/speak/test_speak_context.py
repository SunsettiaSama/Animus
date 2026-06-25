from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.pipelines.request_driven.orchestrator import SpeakOrchestrator
from agent.soul.speak.pipelines.request_driven.orchestrator.guidance.context import (
    SpeakContextDistiller,
    normalize_one_sentence,
    render_dialogue_compressed,
)


def test_render_dialogue_compressed_is_internal_probe_format():
    block = render_dialogue_compressed(["user greeted", "discussed speak module"])
    assert "\u3010\u5f53\u524d\u5bf9\u8bdd\u00b7\u538b\u7f29\u3011" not in block
    assert "user greeted" in block
    assert block.startswith("- ")


def test_normalize_one_sentence_keeps_single_line():
    assert normalize_one_sentence("\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\u3002") == "\u7b2c\u4e00\u53e5\u3002"
    assert normalize_one_sentence("  hello world  \nmore") == "hello world"


def test_distiller_triggers_every_k_chunks():
    distilled_batches: list[tuple[tuple[str, str], ...]] = []
    done = threading.Event()

    def distill_fn(batch, prior):
        distilled_batches.append(tuple(batch))
        done.set()
        return f"batch-{len(distilled_batches)}"

    distiller = SpeakContextDistiller(
        chunk_size=2,
        distill_fn=distill_fn,
        submit=lambda task: task(),
    )

    distiller.on_turn("tao", "u1", "a1")
    assert distiller.prompt_block("tao") == ""
    distiller.on_turn("tao", "u2", "a2")
    done.wait(timeout=1.0)

    block = distiller.prompt_block("tao")
    assert "batch-1" in block
    assert len(distilled_batches) == 1
    assert distilled_batches[0] == (("u1", "a1"), ("u2", "a2"))


def _mock_presence_snap():
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    return snap


def test_compose_uses_working_memory_block_not_status_dialogue():
    persona = MagicMock()
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = MagicMock()
    presence.snapshot.return_value = _mock_presence_snap()

    distiller = SpeakContextDistiller(chunk_size=2, distill_fn=lambda batch, prior: "")
    composer = SpeakOrchestrator(persona, presence, context_distiller=distiller)

    bundle_before = composer.compose("tao", "new question", generation=1)
    assert "\u3010\u5f53\u524d\u4f1a\u8bdd\u00b7\u5de5\u4f5c\u8bb0\u5fc6\u3011" not in bundle_before.build_system()

    distiller.on_turn("tao", "u1", "a1")
    distiller.on_turn("tao", "u2", "a2")

    state = distiller._session("tao")
    with state.lock:
        state.distilled.append("two turns of small talk")

    bundle_after = composer.compose("tao", "new question", generation=1)
    system = bundle_after.build_system()
    assert "\u3010\u5f53\u524d\u4f1a\u8bdd\u00b7\u5de5\u4f5c\u8bb0\u5fc6\u3011" in system
    assert "two turns of small talk" in system
    assert bundle_after.scene.dialogue_compressed == ""


def test_async_compose_does_not_wait_for_pending_distill():
    started = threading.Event()
    release = threading.Event()

    def slow_distill(batch, prior):
        started.set()
        release.wait(timeout=1.0)
        return "async done"

    distiller = SpeakContextDistiller(
        chunk_size=2,
        distill_fn=slow_distill,
        submit=lambda task: threading.Thread(target=task, daemon=True).start(),
    )
    distiller.on_turn("tao", "u1", "a1")
    distiller.on_turn("tao", "u2", "a2")
    started.wait(timeout=1.0)

    block = distiller.prompt_block("tao")
    assert block == ""

    release.set()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        block = distiller.prompt_block("tao")
        if "async done" in block:
            break
        time.sleep(0.01)
    assert "async done" in block
