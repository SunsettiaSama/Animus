"""blocks/context 模块冒烟：蒸馏前后 snapshot 与 apply 写入 bundle 的字段。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.context import ContextBlock, context_snapshot
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.core.base import BlockContext
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance import (
    SpeakContextDistiller,
    SpeakGuidanceLayer,
)
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.persona import SpeakPersonaLayer
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.scene import SpeakSceneLayer
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.system import build_system_layer, SpeakReplyStyle
from agent.soul.speak.pipelines.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.pipelines.request_driven.orchestrator.director.decide import decide_plan
from agent.soul.speak.pipelines.request_driven.orchestrator.orchestrator import SpeakOrchestrator
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

SRC = Path(__file__).resolve().parent.parent.parent.parent
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.context import ContextBlock, context_snapshot
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.core.base import BlockContext
from agent.soul.speak.pipelines.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.pipelines.request_driven.orchestrator.director.decide import decide_plan
from agent.soul.speak.pipelines.request_driven.orchestrator.orchestrator import SpeakOrchestrator
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

SESSION = "ctx-smoke"
TURNS = (
    ("你好，今天天气不错", "是啊，阳光很好。"),
    ("我们聊聊 speak 模块吧", "好，compose 管线最近在做 block 化。"),
    ("context block 负责什么？", "主要是会话蒸馏和工作记忆写入 bundle。"),
    ("那蒸馏什么时候触发？", "buffer 满 chunk_size 后由 director refresh 触发。"),
)


def _mock_presence():
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    return snap


def _block_ctx(orchestrator: SpeakOrchestrator, *, turn_index: int, user_text: str) -> BlockContext:
    pipe = orchestrator.pipeline_context(
        session_id=SESSION,
        turn_index=turn_index,
        user_text=user_text,
        generation=1,
    )
    return pipe.to_block_context()


def _bundle(user_text: str) -> SpeakPromptBundle:
    style = SpeakReplyStyle()
    return SpeakPromptBundle(
        session_id=SESSION,
        mode="inbound",
        system=build_system_layer(mode="inbound", output_format=style.render_prompt()),
        persona=SpeakPersonaLayer(),
        scene=SpeakSceneLayer(),
        guidance=SpeakGuidanceLayer(),
        user_text=user_text,
        reply_style=style,
    )


def test_blocks_context_distill_smoke(capsys):
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="莉奈娅")
    presence = MagicMock()
    presence.snapshot.return_value = _mock_presence()

    distiller = SpeakContextDistiller(chunk_size=4, submit=lambda task: task())
    orchestrator = SpeakOrchestrator(persona, presence, context_distiller=distiller)
    block = ContextBlock()

    ctx0 = _block_ctx(orchestrator, turn_index=1, user_text=TURNS[0][0])
    bundle0 = _bundle(TURNS[0][0])
    plan0 = decide_plan(
        orchestrator,
        session_id=SESSION,
        target_turn_index=1,
        user_text=TURNS[0][0],
        generation=1,
        cold_start=True,
    )
    dec0 = plan0.decision_for("context")
    block.apply(ctx0, dec0, bundle0, plan=plan0)
    assert bundle0.guidance.context_distill == ""
    assert bundle0.guidance.working_memory == ""

    for u, a in TURNS[:3]:
        distiller.on_turn(SESSION, u, a)
    ctx3 = _block_ctx(orchestrator, turn_index=4, user_text=TURNS[3][0])
    bundle3 = _bundle(TURNS[3][0])
    plan3 = decide_plan(
        orchestrator,
        session_id=SESSION,
        target_turn_index=4,
        user_text=TURNS[3][0],
        generation=1,
    )
    dec3 = plan3.decision_for("context")
    block.apply(ctx3, dec3, bundle3, plan=plan3)
    assert "尚未纳入上述摘要" in bundle3.guidance.working_memory
    assert bundle3.guidance.context_distill == ""
    assert context_snapshot(ctx3).extra["buffer_count"] == 3

    distiller.on_turn(SESSION, *TURNS[3])
    pre = distiller.snapshot(SESSION)
    assert pre["pending_jobs"] == 1
    assert pre["buffer_count"] == 0

    assert distiller.distill_if_requested(SESSION) is True
    post = distiller.snapshot(SESSION)
    assert post["distilled_count"] == 1

    user_after = "继续说说 context block 的设计"
    ctx4 = _block_ctx(orchestrator, turn_index=5, user_text=user_after)
    bundle4 = _bundle(user_after)
    plan4 = decide_plan(
        orchestrator,
        session_id=SESSION,
        target_turn_index=5,
        user_text=user_after,
        generation=1,
    )
    dec4 = plan4.decision_for("context")
    block.apply(ctx4, dec4, bundle4, plan=plan4)

    print("\n=== blocks/context 冒烟 ===")
    print("蒸馏前 buffer:", json.dumps(pre, ensure_ascii=False))
    print("蒸馏后 distilled:", json.dumps(post, ensure_ascii=False))
    print("context_distill:", bundle4.guidance.context_distill)
    print("working_memory:", bundle4.guidance.working_memory or "(空)")
    print("dialogue_compressed:", bundle4.persona.dialogue_compressed)

    assert "在此之前，你们已经谈过的脉络" in bundle4.guidance.context_distill
    assert bundle4.persona.dialogue_compressed.startswith("- ")
    assert dec4.include is True

    out = capsys.readouterr().out
    assert "blocks/context 冒烟" in out


def _resolve_live_llm(request: pytest.FixtureRequest):
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM

    base_url = (request.config.getoption("--speak-base-url") or "").strip()
    api_key = (request.config.getoption("--speak-api-key") or "").strip()
    model = (request.config.getoption("--speak-model") or "").strip()

    if not base_url or not api_key or not model:
        yaml_path = SRC.parent / "config" / "llm_core" / "config.yaml"
        if yaml_path.is_file():
            cfg = LLMConfig.from_yaml(str(yaml_path))
            if cfg.api_key.strip() and cfg.model.strip():
                if not base_url and cfg.base_url:
                    base_url = cfg.base_url.strip()
                if not api_key:
                    api_key = cfg.api_key.strip()
                if not model:
                    model = cfg.model.strip()

    if not base_url or not api_key or not model:
        pytest.skip(
            "需要 --speak-base-url / --speak-api-key / --speak-model，"
            "或可读的 config/llm_core/config.yaml"
        )

    return OpenAILLM(
        LLMConfig(
            backend="openai",
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_tokens=512,
            temperature=0.7,
        )
    )


def _build_live_stack(request: pytest.FixtureRequest):
    persona = MagicMock()
    snap = persona_snapshot_with_distill(name="莉奈娅")
    persona.get_persona_snapshot.return_value = snap
    dialogue = snap.get("persona_distill", {}).get("slices", {}).get("dialogue", "")
    presence = MagicMock()
    presence.snapshot.return_value = _mock_presence()

    engine = SpeakLLMEngine(_resolve_live_llm(request))
    distiller = SpeakContextDistiller(
        llm_engine=engine,
        chunk_size=4,
        submit=lambda task: task(),
    )
    if dialogue.strip():
        distiller.set_agent_persona_provider(lambda: dialogue.strip())
    orchestrator = SpeakOrchestrator(persona, presence, context_distiller=distiller)
    return orchestrator, distiller, engine


@pytest.mark.network
def test_blocks_context_distill_smoke_live(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--run-speak-live"):
        pytest.skip("加 --run-speak-live 以接真实 LLM 试跑 context 蒸馏")

    orchestrator, distiller, _engine = _build_live_stack(request)
    block = ContextBlock()
    session = "ctx-live-smoke"

    for u, a in TURNS:
        distiller.on_turn(session, u, a)

    pre = distiller.snapshot(session)
    print("\n=== blocks/context live · 蒸馏前 ===")
    print(json.dumps(pre, ensure_ascii=False, indent=2))

    pumped = distiller.distill_if_requested(session)
    post = distiller.snapshot(session)
    print("\n=== blocks/context live · 蒸馏后（LLM structured_distill） ===")
    print(f"distill_if_requested={pumped}")
    print(json.dumps(post, ensure_ascii=False, indent=2))

    user_after = "继续说说 context block 的设计"
    ctx = orchestrator.pipeline_context(
        session_id=session,
        turn_index=5,
        user_text=user_after,
        generation=1,
    ).to_block_context()
    snap = context_snapshot(ctx)
    bundle = _bundle(user_after)
    bundle.session_id = session
    plan = decide_plan(
        orchestrator,
        session_id=session,
        target_turn_index=5,
        user_text=user_after,
        generation=1,
    )
    dec = plan.decision_for("context")
    assert dec is not None
    block.apply(ctx, dec, bundle, plan=plan)

    print("\n=== blocks/context live · snapshot → apply 写入 ===")
    print(json.dumps({"block": snap.block, "summary": snap.summary, "extra": snap.extra}, ensure_ascii=False, indent=2))
    print(f"director: refresh={dec.refresh}, include={dec.include}, reason={dec.reason}")
    print("\n--- bundle.guidance.context_distill ---")
    print(bundle.guidance.context_distill or "(空)")
    print("\n--- bundle.guidance.working_memory ---")
    print(bundle.guidance.working_memory or "(空)")
    print("\n--- bundle.persona.dialogue_compressed ---")
    print(bundle.persona.dialogue_compressed or "(空)")

    distilled = post.get("distilled", [])
    assert isinstance(distilled, list) and len(distilled) >= 1
    summary = str(distilled[0]).strip()
    assert summary, "LLM 蒸馏摘要不能为空"
    assert len(summary) >= 8, f"蒸馏摘要过短: {summary!r}"
    assert "在此之前，你们已经谈过的脉络" in bundle.guidance.context_distill
    assert summary[:80] in bundle.guidance.context_distill or summary in bundle.guidance.context_distill
    assert bundle.persona.dialogue_compressed.startswith("- ")
    assert "你" in summary or "今天" in summary or "speak" in summary.lower()
