from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.compose import SpeakPromptComposer
from agent.soul.speak.compose.context import (
    SpeakContextDistiller,
    normalize_one_sentence,
    render_dialogue_compressed,
)


def test_render_dialogue_compressed_labels_session_summary():
    block = render_dialogue_compressed(["用户问候并聊起架构", "讨论了 speak 模块设计"])
    assert "【当前对话·压缩】" in block
    assert "已蒸馏" in block
    assert "用户问候并聊起架构" in block


def test_normalize_one_sentence_keeps_single_line():
    assert normalize_one_sentence("第一句。第二句。") == "第一句。"
    assert normalize_one_sentence("  hello world  \nmore") == "hello world"


def test_distiller_triggers_every_k_chunks():
    distilled_batches: list[tuple[tuple[str, str], ...]] = []
    done = threading.Event()

    def distill_fn(batch, prior):
        distilled_batches.append(tuple(batch))
        done.set()
        return f"压缩第{len(distilled_batches)}批"

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
    assert "压缩第1批" in block
    assert len(distilled_batches) == 1
    assert distilled_batches[0] == (("u1", "a1"), ("u2", "a2"))


def test_compose_uses_completed_distillation_only():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {
        "profile": {"name": "小A"},
        "self_concept": {},
    }
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    presence.snapshot.return_value = snap

    distiller = SpeakContextDistiller(chunk_size=2, distill_fn=lambda batch, prior: "")
    composer = SpeakPromptComposer(persona, presence, context_distiller=distiller)

    bundle_before = composer.compose("tao", "新问题")
    assert "【当前对话·压缩】" not in bundle_before.build_system()

    distiller.on_turn("tao", "u1", "a1")
    distiller.on_turn("tao", "u2", "a2")

    state = distiller._session("tao")
    with state.lock:
        state.distilled.append("用户连续两轮寒暄。")

    bundle_after = composer.compose("tao", "新问题")
    system = bundle_after.build_system()
    assert "【当前对话·压缩】" in system
    assert "用户连续两轮寒暄。" in system


def test_async_compose_does_not_wait_for_pending_distill():
    started = threading.Event()
    release = threading.Event()

    def slow_distill(batch, prior):
        started.set()
        release.wait(timeout=1.0)
        return "异步压缩完成。"

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
        if "异步压缩完成" in block:
            break
        time.sleep(0.01)
    assert "异步压缩完成" in block
