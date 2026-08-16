"""编剧 Agent live：注入完整书写材料，观察多步查阅后产出约十个 unit。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import paths
from config.llm_core.config import LLMConfig
from infra.llm import LLM

from agent.soul.speak.responders.request_driven.directors.base import DirectorLLMCaller
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    StateStore,
)
from agent.soul.speak.responders.request_driven.screenwriter.materials import (
    build_writing_materials,
)
from agent.soul.speak.responders.request_driven.screenwriter.writer import Screenwriter


def _rich_materials() -> dict:
    now = time.time()
    clay = build_writing_materials(
        compose_meta={
            "persona_brief": (
                "角色安静、手稳，喜欢把物件摆齐；说话前会先摸一摸手里的东西。"
            ),
            "dynamic_memory_ids": [
                "mem-thistle",
                "mem-lamp",
                "mem-leaf",
                "mem-rain",
                "mem-guest",
            ],
            "dynamic_memory_texts": [
                "昨夜在标本台整理蓟花标本，压纸还没换干净",
                "帐篷角落有一盏暖色台灯，灯罩边缘有一道旧划痕",
                "桌上散着几片带横纹的干叶，像潮退后的沙滩纹理",
                "傍晚雨敲过篷顶，水珠从绳结处慢慢滑下",
                "上次有人问起花萼，自己只点了点头，没把镊子递过去",
            ],
            "dynamic_share_texts": [
                "想聊聊干叶上的横纹像不像潮水退去后的沙滩",
                "想说台灯一亮，标本台就变得很近",
            ],
            "world_brief": "野外帐篷营地，夜里主要靠灯工作。",
            "character_feedback_to_screenwriter": [
                {"text": "镊子有点滑，想先擦一下再继续"},
            ],
        },
        fate_speak_desire=62,
        fate_tendency="愿意接话",
        presence_mood="平静",
        presence_brief="在标本台前整理",
        grounded=(
            "场景：帐篷内标本台。桌上有蓟花标本、压纸、镊子、吸水纸；"
            "角落台灯亮着，篷外偶有水声。"
        ),
        world_brief="野外帐篷营地，夜里主要靠灯工作。",
        dialogue_history=(
            "（新会话）来访者刚进帐篷，尚未开口；角色仍低头对着标本台。"
        ),
        recent_turns=(),
        silence_log=(
            "静默｜角色指腹摩挲压纸边缘",
            "静默｜台灯发出细微电流声",
        ),
        last_user_text="",
        last_user_speak_at=0.0,
        last_agent_speak_at=now - 120.0,
        scene_seeds=(
            "蓟花",
            "标本台",
            "台灯",
            "干叶",
            "压纸",
            "镊子",
            "帐篷",
            "暖光",
            "花萼",
            "吸水纸",
        ),
    )
    return clay.as_dict(), clay


def main() -> None:
    cfg_path = paths.llm_config_yaml
    if not cfg_path.exists():
        raise FileNotFoundError(f"missing llm config: {cfg_path}")
    cfg = LLMConfig.from_yaml(str(cfg_path))
    llm = LLM(cfg)
    caller = DirectorLLMCaller(llm=llm, timeout_sec=90.0)
    if not caller.available:
        raise RuntimeError("director llm unavailable")

    store = StateStore()
    state = store.session("screenwriter-agent-live")
    sw = Screenwriter(llm=caller, target_units=10)
    materials, clay = _rich_materials()

    print("[screenwriter-agent] init via multi-step agent …")
    out = sw.init_presence(
        state,
        session_id="screenwriter-agent-live",
        user_text="",
        turn_index=0,
        materials=materials,
        speak_desire=62,
    )
    agent_snap = state.director_cache.get("screenwriter_agent") or {}

    consumed = []
    while state.plot_arc.ready and state.plot_arc.live_unit_count() >= 5:
        prev = state.plot_arc.active_unit()
        if prev is None:
            break
        consumed.append(prev.intent)
        sw.confirm_interaction_unit_complete(
            state,
            poll_seq=1,
            reason="live_probe_consume",
        )
        if len(consumed) >= 8:
            break

    state.poll_seq = 4
    print(
        f"[screenwriter-agent] after consume live={state.plot_arc.live_unit_count()} "
        f"history={len(state.plot_arc.unit_history)} → tick refill …"
    )
    refill_out = sw.tick_on_poll(
        state,
        session_id="screenwriter-agent-live",
        turn_index=1,
        materials=materials,
        dialogue_history="用户还没开口；角色继续手头标本。",
        force=False,
        async_write=False,
        speak_desire=62,
    )
    agent_refill = state.director_cache.get("screenwriter_agent") or {}

    arc = state.plot_arc.snapshot() if state.plot_arc.ready else {}
    report = {
        "llm_model": cfg.model,
        "used_fallback_init": bool(getattr(out, "used_fallback", False)),
        "reason_init": getattr(out, "reason", ""),
        "agent_init": agent_snap,
        "agent_after_refill": agent_refill,
        "writing_materials_preview": clay.render_for_screenwriter()[:1600],
        "narrative_opening": state.director_cache.get("narrative_opening"),
        "scene_seeds": state.director_cache.get("scene_seeds"),
        "consumed_units": consumed,
        "plot_arc": arc,
        "unit_count_live": state.plot_arc.live_unit_count() if state.plot_arc.ready else 0,
        "unit_count_history": len(state.plot_arc.unit_history) if state.plot_arc.ready else 0,
        "plot_flow": state.plot_flow.snapshot() if state.plot_flow.ready else None,
        "material_schedule": {
            "inject_memory": state.plot_flow.inject_memory,
            "memory_unit_ids": list(state.plot_flow.memory_unit_ids),
            "inject_share": state.plot_flow.inject_share,
            "share_indices": list(state.plot_flow.share_indices),
            "material_reason": state.plot_flow.material_reason,
        },
        "refill": {
            "ran": refill_out is not None,
            "reason": getattr(refill_out, "reason", None) if refill_out else None,
            "live_after": state.plot_arc.live_unit_count() if state.plot_arc.ready else 0,
            "history_after": len(state.plot_arc.unit_history) if state.plot_arc.ready else 0,
        },
        "notes": [n for n in state.notes if "screenwriter" in str(n)],
    }

    out_path = Path(__file__).with_name("screenwriter_agent_live_output.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[screenwriter-agent] wrote {out_path}")
    print("--- agent steps (init) ---")
    for i, step in enumerate(agent_snap.get("steps") or [], 1):
        print(f"  {i}. action={step.get('action')} think={str(step.get('think') or '')[:80]}")
        print(f"     obs={str(step.get('observation') or '')[:120]}")
    print("--- opening ---")
    print(report["narrative_opening"] or "(empty)")
    print("--- summary ---")
    print((arc or {}).get("summary") or "(empty)")
    print("--- live units ---")
    for u in (arc or {}).get("units") or []:
        print(f"  - [{u.get('status')}] {u.get('intent')}")
    print(f"live={report['unit_count_live']} history={report['unit_count_history']}")
    print("--- schedule ---")
    print(report["material_schedule"])
    print("--- refill ---")
    print(report["refill"])
    for i, step in enumerate(agent_refill.get("steps") or [], 1):
        print(f"  refill {i}. action={step.get('action')} think={str(step.get('think') or '')[:80]}")


if __name__ == "__main__":
    main()
