"""blocks/context 冒烟脚本：打印蒸馏前后 snapshot 与 bundle 写入字段。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.orchestrator.blocks.context import ContextBlock, context_snapshot
from agent.soul.speak.orchestrator.blocks.core.base import BlockContext
from agent.soul.speak.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.orchestrator.director.decide import decide_plan
from agent.soul.speak.orchestrator.guidance.context import SpeakContextDistiller
from agent.soul.speak.orchestrator.guidance.layer import SpeakGuidanceLayer
from agent.soul.speak.orchestrator.orchestrator import SpeakOrchestrator
from agent.soul.speak.orchestrator.persona import SpeakPersonaLayer
from agent.soul.speak.orchestrator.scene import SpeakSceneLayer
from agent.soul.speak.orchestrator.system.build import build_system_layer
from agent.soul.speak.orchestrator.system.reply_style import SpeakReplyStyle
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


def _dump(label: str, distiller: SpeakContextDistiller, snap, bundle: SpeakPromptBundle | None) -> None:
    raw = distiller.snapshot(SESSION)
    print(f"\n{'=' * 60}")
    print(label)
    print(f"{'=' * 60}")
    print("distiller.snapshot:")
    print(json.dumps(raw, ensure_ascii=False, indent=2))
    print("context_snapshot (blocks/context/snapshot.py):")
    print(json.dumps({"block": snap.block, "summary": snap.summary, "extra": snap.extra}, ensure_ascii=False, indent=2))
    if bundle is not None:
        print("--- bundle 写入 (blocks/context/apply.py) ---")
        print(f"guidance.context_distill:\n{bundle.guidance.context_distill or '(空)'}")
        print(f"guidance.working_memory:\n{bundle.guidance.working_memory or '(空)'}")
        print(f"persona.dialogue_compressed:\n{bundle.persona.dialogue_compressed or '(空)'}")


def main() -> None:
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="莉奈娅")
    presence = MagicMock()
    presence.snapshot.return_value = _mock_presence()

    # llm=None → structured_distill 走 fallback，无需真实 API
    distiller = SpeakContextDistiller(chunk_size=4, submit=lambda task: task())
    orchestrator = SpeakOrchestrator(persona, presence, context_distiller=distiller)
    block = ContextBlock()

    # 1) 空会话
    ctx0 = _block_ctx(orchestrator, turn_index=1, user_text=TURNS[0][0])
    snap0 = context_snapshot(ctx0)
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
    _dump("阶段 A：蒸馏前（空会话）", distiller, snap0, bundle0)
    print(f"director context decision: refresh={dec0.refresh}, include={dec0.include}, reason={dec0.reason}")

    # 2) 累积 3 轮，buffer 未满
    for u, a in TURNS[:3]:
        distiller.on_turn(SESSION, u, a)
    ctx3 = _block_ctx(orchestrator, turn_index=4, user_text=TURNS[3][0])
    snap3 = context_snapshot(ctx3)
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
    _dump("阶段 B：蒸馏前（3 轮在 buffer，未触发压缩）", distiller, snap3, bundle3)
    print(f"director context decision: refresh={dec3.refresh}, include={dec3.include}, reason={dec3.reason}")

    # 3) 第 4 轮入队 → distill_if_requested（模拟 director refresh）
    distiller.on_turn(SESSION, *TURNS[3])
    ctx4 = _block_ctx(orchestrator, turn_index=5, user_text="继续说说 context block 的设计")
    snap_pre = context_snapshot(ctx4)
    print(f"\n{'=' * 60}")
    print("阶段 C：第 4 轮入队后、蒸馏执行前")
    print(f"{'=' * 60}")
    print("queued 待蒸馏:", json.dumps(distiller.snapshot(SESSION), ensure_ascii=False, indent=2))

    pumped = distiller.distill_if_requested(SESSION)
    snap_post = context_snapshot(ctx4)
    bundle4 = _bundle("继续说说 context block 的设计")
    plan4 = decide_plan(
        orchestrator,
        session_id=SESSION,
        target_turn_index=5,
        user_text="继续说说 context block 的设计",
        generation=1,
    )
    dec4 = plan4.decision_for("context")
    block.refresh(ctx4, dec4, target=MagicMock(), plan=plan4)
    block.apply(ctx4, dec4, bundle4, plan=plan4)
    _dump("阶段 D：蒸馏后（fallback 压缩完成）", distiller, snap_post, bundle4)
    print(f"distill_if_requested 返回: {pumped}")
    print(f"director context decision: refresh={dec4.refresh}, include={dec4.include}, reason={dec4.reason}")

    distilled = distiller.snapshot(SESSION).get("distilled", [])
    assert isinstance(distilled, list) and len(distilled) == 1
    assert bundle4.guidance.context_distill
    assert bundle4.persona.dialogue_compressed
    print("\n[OK] blocks/context 冒烟通过")


if __name__ == "__main__":
    main()
