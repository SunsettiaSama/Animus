#!/usr/bin/env python3
"""复杂示例：预编排剧情 unit 消费队列 + 多轮用户打断下的角色扮演。

流程：
1) 编剧侧准备 4 步 plot_arc
2) seed_plot_unit_consumption_queue 预编排可执行开口
3) 每轮用户发言 → 绑定当前 active 剧情步 → 角色生成 → 消费推进队列
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


COMPLEX_TURNS = (
    {
        "user": "喂喂，在吗？我刚到营地外围，你帐篷里还好吗？",
        "expect": "一边动手一边短回，不放下锁扣",
    },
    {
        "user": "别拧了，听我的——直接拿刀撬开不就完了？",
        "expect": "拒绝蛮力，坚持沿横纹缓旋",
    },
    {
        "user": "外面好像有动静，你要不要先出来看看？",
        "expect": "可分心一瞬，但仍以确认阻力/蜡膜为主",
    },
    {
        "user": "晚上火锅还是烧烤？快点选一个嘛～",
        "expect": "不合时宜：短挡或语气词，继续核对针尖",
    },
)


def _sep(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}", flush=True)


def _load_engine(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM
    from agent.soul.speak.llm.engine import SpeakLLMEngine

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
        raise SystemExit("missing api_key/model")
    print(f"model={model}")
    print(f"base_url={base_url or '(default)'}")
    return SpeakLLMEngine(
        OpenAILLM(
            LLMConfig(
                backend="openai",
                model=model,
                api_key=api_key,
                base_url=base_url or None,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
        )
    )


def _build_state():
    from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
        seed_plot_unit_consumption_queue,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
        CharacterRhythmSchedule,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    arc = PlotArc(
        summary="晨光渐亮：在标本台旋开金属锁扣，全程保护蜡膜与第十八格针尖对齐；露米在帐帘警戒。",
        evidence="书签边缘、槽口横纹、蜡膜划痕偏角、针尖凸起、帐外灌木",
        units=[
            InteractionUnit(
                intent="用书签边缘抵住锁扣槽口，找准横纹末端",
                evidence="锁扣卡到位未开",
                span_polls=2,
            ),
            InteractionUnit(
                intent="沿横纹暗示方向缓旋，分辨阻力是卡死还是可松",
                evidence="偏转约两度仍有阻力",
                span_polls=2,
            ),
            InteractionUnit(
                intent="阻力若松动则继续旋，同时确认蜡膜未裂开",
                evidence="蜡膜原位是硬约束",
                span_polls=2,
            ),
            InteractionUnit(
                intent="旋开后立刻核对第十八格针尖仍对准槽口",
                evidence="对齐丢失则前功尽弃",
                span_polls=2,
            ),
        ],
    )
    arc._activate_head(poll_seq=0)
    rhythm = seed_plot_unit_consumption_queue(
        CharacterRhythmSchedule(),
        now=time.time(),
        plot_arc=arc,
    )
    return SimpleNamespace(
        plot_arc=arc,
        plot_flow=None,
        character_rhythm_schedule=rhythm,
        director_cache={},
        pending_character_handoff=None,
        poll_seq=0,
        notes=[],
        narrative_card=SimpleNamespace(
            interaction_mode="",
            user_activity="",
            user_identity="营地外的熟人",
            scene_event="",
        ),
        presence_card=SimpleNamespace(
            ready=True,
            mood="专注，略紧",
            brief="锁扣事关标本，不该被闲聊扯走。",
            speak_desire=40,
            fate_tendency="克制开口",
            render=lambda: "心情：专注，略紧\n开口欲：40/100（克制开口）",
        ),
        silence_log=SimpleNamespace(ready=False, render=lambda: ""),
    )


def _print_queue(state, label: str) -> None:
    arc = state.plot_arc
    rhythm = state.character_rhythm_schedule
    print(f"\n[{label}]")
    print(f"  plot_arc.active={arc.active_unit().intent if arc.active_unit() else '∅'}")
    for i, u in enumerate(arc.units):
        mark = {"active": "*", "pending": ".", "done": "x"}.get(u.status, "?")
        print(f"  {mark} [{i}] {u.status:8} {u.intent}")
    pending = [e for e in rhythm.executable_units if e.status == "pending"]
    consumed = [e for e in rhythm.executable_units if e.status == "consumed"]
    print(f"  exec pending={len(pending)} consumed={len(consumed)}")
    for e in sorted(rhythm.executable_units, key=lambda x: x.open_at):
        pids = ",".join(e.plot_unit_ids) if e.plot_unit_ids else "—"
        print(
            f"    - {e.status:9} reason={e.reason:16} "
            f"plot={pids[:18]} script={(e.script_text or '')[:40]}"
        )


def _base_system() -> str:
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.role import (
        build_role,
    )

    persona = (
        "【身份】你是莉奈娅（Linnea）。说话短句、带自然比喻。"
        "你在帐篷标本台前处理锁扣；露米在帐帘旁。晨光越来越亮，时间紧。"
    )
    return f"{build_role('inbound')}\n\n{persona}"


def _run_turn(engine, state, *, user_text: str, turn_index: int, base: str):
    from agent.soul.speak.responders.request_driven.character.consume import (
        advance_plot_queue_on_delivery,
    )
    from agent.soul.speak.responders.request_driven.character.context import (
        bind_delivery_step_for_user,
        build_narrative_snapshot,
    )
    from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
        DynamicLayerMaterials,
        DynamicLayerSchedule,
    )
    from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
        RoleContextView,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
        plot_progress_fingerprint,
    )
    from agent.soul.speak.responders.request_driven.prompt import build_role_prompt

    step_id, plot_ids, _ = bind_delivery_step_for_user(
        state,
        session_id="complex-plot-queue",
        turn_index=turn_index,
    )
    narrative = build_narrative_snapshot(
        state,
        origin="user",
        user_text=user_text,
    )
    prompt = build_role_prompt(
        RoleContextView(session_id="complex-plot-queue"),
        user_text=user_text,
        materials=DynamicLayerMaterials(session_id="complex-plot-queue"),
        schedule=DynamicLayerSchedule(reason="complex_plot_queue"),
        interaction_channel=narrative.interaction_channel,
        plot_outline_text=narrative.plot_outline_text,
        plot_flow_text=(
            f"此刻步骤：{state.plot_arc.active_unit().intent}"
            if state.plot_arc.active_unit()
            else ""
        ),
        presence_mood=narrative.presence_mood,
        presence_brief=narrative.presence_brief,
        presence_speak_desire=narrative.presence_speak_desire,
        presence_fate_tendency=narrative.presence_fate_tendency,
        user_identity=narrative.user_identity,
        user_activity=narrative.user_activity,
    )
    system = f"{base}\n\n{prompt.system_extra}".strip()
    raw = engine.generate(user_text, system=system).text

    # 模拟交付成功：消费 executable + 推进 plot_arc
    fp = plot_progress_fingerprint(state.plot_arc, state.plot_flow)
    state.character_rhythm_schedule.mark_consumed(
        step_id,
        turn_index=turn_index,
        trigger_id=f"user:complex:{turn_index}",
        plot_fingerprint=fp,
        script_text=next(
            (
                e.script_text
                for e in state.character_rhythm_schedule.executable_units
                if e.unit_id == step_id
            ),
            "",
        ),
        answer_fingerprint=raw[:120],
    )
    next_intent = advance_plot_queue_on_delivery(
        state,
        plot_unit_ids=plot_ids,
        reason=f"complex_turn_{turn_index}",
    )
    return raw, step_id, plot_ids, next_intent


def main() -> int:
    parser = argparse.ArgumentParser(description="Complex plot-queue character live smoke")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.7)
    args = parser.parse_args()

    _sep("load LLM")
    engine = _load_engine(args)
    state = _build_state()
    base = _base_system()

    _sep("预编排剧情 unit 消费队列")
    _print_queue(state, "seed")

    for i, turn in enumerate(COMPLEX_TURNS, start=1):
        _sep(f"Turn {i}/{len(COMPLEX_TURNS)}  expect={turn['expect']}")
        print(f"USER: {turn['user']}")
        active = state.plot_arc.active_unit()
        print(f"ACTIVE_BEFORE: {active.intent if active else '∅'}")
        raw, step_id, plot_ids, next_intent = _run_turn(
            engine,
            state,
            user_text=turn["user"],
            turn_index=i,
            base=base,
        )
        print(f"\n--- raw ---\n{raw}")
        print(
            f"\nbound exec={step_id} plot_ids={plot_ids} "
            f"next_intent={next_intent or '∅'}"
        )
        _print_queue(state, f"after_turn_{i}")

    _sep("done")
    done = sum(1 for u in state.plot_arc.units if u.status == "done")
    print(f"plot units done={done}/{len(state.plot_arc.units)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
