#!/usr/bin/env python3
"""导演真实 API 冒烟：挂 DeepSeek，跑 poll / 用户 fast+slow，打印关键产出。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _sep(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}", flush=True)


def _preview(obj: Any, *, limit: int = 1200) -> str:
    if obj is None:
        return "—"
    if isinstance(obj, str):
        text = obj
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(text) > limit:
        return text[:limit] + f"\n…(+{len(text) - limit} chars)"
    return text


def _load_llm(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM

    cfg_path = ROOT / "config" / "llm_core" / "config.yaml"
    cfg = LLMConfig.from_yaml(str(cfg_path)) if cfg_path.is_file() else LLMConfig()
    api_key = (
        args.api_key
        or os.environ.get("SPEAK_SMOKE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or cfg.api_key
        or ""
    ).strip()
    model = (args.model or os.environ.get("SPEAK_SMOKE_MODEL") or cfg.model or "").strip()
    base_url = (
        args.base_url
        or os.environ.get("SPEAK_SMOKE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or cfg.base_url
        or ""
    ).strip()
    if not api_key or not model:
        raise SystemExit("missing api_key/model：检查 config/llm_core/config.yaml 或 --api-key/--model")
    print(f"model={model}")
    print(f"base_url={base_url or '(default)'}")
    return OpenAILLM(
        LLMConfig(
            backend="openai",
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
    )


def _persona_snapshot() -> dict[str, Any]:
    return {
        "profile": {
            "name": "莉奈娅",
            "core_traits": ["好奇", "俏皮", "谨慎"],
            "built": True,
            "built_at": "smoke",
        },
        "self_concept": {
            "narrative": "你是妖精族换生灵，眼下在帐篷里研究标本台锁扣。",
            "beliefs": [],
        },
        "attention_keywords": ["锁扣", "书签", "露米"],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "director-live|",
            "distilled_at": "2026-08-16T00:00:00+00:00",
            "slices": {
                "general": "你是博物学家莉奈娅，说话带自然比喻，短句，不端着。",
                "dialogue": "通过通信设备与对方文字往来；可一边动手一边发消息。",
                "story": "晨光下的标本台，锁扣卡到位未开，横纹暗示旋转方向。",
                "reasoning": "先观察再试探，留意露米与帐外动静。",
                "memory_anchor": "书签边缘、蜡膜划痕、第十八格针尖。",
            },
        },
    }


def _presence_snapshot() -> MagicMock:
    from agent.soul.presence.share_desire import ShareDesire

    snap = MagicMock()
    snap.state.affect.render.return_value = "专注而略紧张"
    snap.state.somatic.render.return_value = "指尖还留着金属触感"
    snap.state.cognition.render.return_value = "在比对横纹与蜡膜偏角"
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = "帐外晨光渐亮"
    snap.state.expectation.toward_user = 0.45
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.2
    return snap


def _build_service(llm):
    from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
    from agent.soul.speak.io.outbound.unit import SpeakAnswer
    from agent.soul.speak.llm.director_engine import SpeakDirectorLLMEngine
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance import (
        SpeakContextDistiller,
    )
    from agent.soul.speak.service import SpeakService
    from agent.soul.speak.session import (
        SpeakTurnChunk,
        resolve_feeling,
        resolve_subjective,
    )

    class _LifeStub:
        def touch_dialogue(self, session_id: str) -> None:
            _ = session_id

        def emit_dialogue_turn(self, chunk: SpeakTurnChunk) -> None:
            _ = chunk

        def record_turn_exchange(self, chunk: SpeakTurnChunk) -> SpeakExchange:
            return SpeakExchange(
                session_id=chunk.session_id,
                question=SpeakQuestion(text=chunk.user_text),
                answer=SpeakAnswer(text=chunk.agent_text),
                subjective=resolve_subjective(chunk),
                feeling=chunk.feeling,
            )

    persona = MagicMock()
    persona.get_persona_snapshot.return_value = _persona_snapshot()
    presence = MagicMock()
    presence.snapshot.return_value = _presence_snapshot()

    engine = SpeakLLMEngine(llm)
    director_engine = SpeakDirectorLLMEngine(llm)
    distiller = SpeakContextDistiller(
        llm_engine=engine,
        chunk_size=2,
        submit=lambda task: task(),
    )
    return SpeakService(
        persona=persona,
        presence=presence,
        llm_engine=engine,
        director_llm_engine=director_engine,
        context_distiller=distiller,
        life_outbound=_LifeStub(),
        life_lifecycle=None,
        context_distill_chunk_size=2,
        typing_idle_ms=50,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
    )


def _print_director_core(service, session_id: str, label: str) -> None:
    state = service._state_store.session(session_id)
    cache = dict(state.director_cache)
    _sep(label)
    print(f"speak_gate={state.speak_gate!r}")
    print(f"presence_card.ready={state.presence_card.ready}")
    print(f"plot_arc.ready={getattr(state.plot_arc, 'ready', False)}")
    if getattr(state.plot_arc, "ready", False):
        print(f"plot_arc.summary={_preview(state.plot_arc.summary, limit=400)}")
        active = state.plot_arc.active_unit() if hasattr(state.plot_arc, "active_unit") else None
        if active is not None:
            print(
                f"active_unit id={getattr(active, 'unit_id', '')!r} "
                f"intent={_preview(getattr(active, 'intent', ''), limit=200)}"
            )
    if getattr(state.plot_flow, "ready", False):
        print(f"plot_flow=\n{_preview(state.plot_flow.render_for_inject(), limit=500)}")
    plan = state.pending_delivery_plan or state.delivery_plan
    print(f"delivery_plan=\n{_preview(plan.snapshot() if plan is not None else None, limit=800)}")
    rhythm = state.character_rhythm_schedule
    print("executable_units:")
    pending = list(rhythm.executable_units or [])
    if not pending:
        print("  （无）")
    for entry in pending:
        print(
            f"  - [{entry.status}] id={entry.unit_id} "
            f"reason={entry.reason or '—'} "
            f"plot={','.join(entry.plot_unit_ids) or '—'}"
        )
        instruction = entry.render_direction()
        if instruction:
            print(instruction)
        else:
            print("    （四条指令为空）")
    print(f"rhythm_schedule=\n{_preview(rhythm.snapshot(), limit=1200)}")
    handoff = state.pending_character_handoff
    print(f"pending_character_handoff=\n{_preview(handoff, limit=600)}")
    keys = (
        "outline",
        "user_intent",
        "turn_delivery",
        "rhythm_schedule",
        "dynamic_layer",
        "module_inject",
        "next_turn_guide",
        "screenwriter",
    )
    slim = {k: cache.get(k) for k in keys if k in cache}
    print(f"director_cache(selected)=\n{_preview(slim, limit=2000)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Director live API smoke")
    parser.add_argument("--session-id", default="director-live-smoke")
    parser.add_argument("--user", default="锁扣那道横纹，你觉得该往哪边拧？我这边先别乱动。")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--skip-poll", action="store_true")
    args = parser.parse_args()

    _sep("load live LLM")
    llm = _load_llm(args)
    service = _build_service(llm)
    coord = service._director_coordinator
    if coord is None:
        raise SystemExit("DirectorCoordinator 未绑定")
    if not service._director_llm.available:
        raise SystemExit("director LLM unavailable")

    sid = args.session_id.strip()
    user_text = args.user.strip()
    service.session_manager.open(sid, trigger="user_message")

    if not args.skip_poll:
        _sep("1) poll_tick idle（编剧/节奏先起势）")
        t0 = time.perf_counter()
        poll_out = coord.on_poll_tick(sid, trigger="idle")
        print(f"latency_ms={int((time.perf_counter() - t0) * 1000)}")
        print(_preview(poll_out, limit=1500))
        progress = service._state_store.session(sid).director_cache.get("plot_progress_check")
        print(f"plot_progress_check=\n{_preview(progress, limit=800)}")
        _print_director_core(service, sid, "after poll_tick")

    _sep("2) on_user_input FAST（清静默 / 必要则 init presence）")
    t0 = time.perf_counter()
    fast_out = coord.on_user_input(sid, user_text, turn_index=1, phase="fast")
    print(f"latency_ms={int((time.perf_counter() - t0) * 1000)}")
    print(_preview(fast_out, limit=1500))
    _print_director_core(service, sid, "after fast")

    _sep("3) on_user_input SLOW（完整导演树，不催生角色正文）")
    t0 = time.perf_counter()
    slow_out = coord.on_user_input(sid, user_text, turn_index=1, phase="slow")
    print(f"latency_ms={int((time.perf_counter() - t0) * 1000)}")
    print(_preview(slow_out, limit=2000))
    _print_director_core(service, sid, "after slow")

    _sep("4) director_snapshot 摘要")
    snap = service.director_snapshot(sid)
    print(f"director_llm_ready={snap.get('director_llm_ready')}")
    print(_preview(snap.get("print"), limit=2500))

    _sep("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
