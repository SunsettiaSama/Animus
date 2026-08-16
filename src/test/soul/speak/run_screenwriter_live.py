"""跑一次真实编剧 init + 轻量补仓，落盘查看产出。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import paths
from config.llm_core.config import LLMConfig
from infra.llm import LLM

from agent.soul.speak.responders.request_driven.directors.base import DirectorLLMCaller
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import StateStore
from agent.soul.speak.responders.request_driven.screenwriter.materials import build_writing_materials
from agent.soul.speak.responders.request_driven.screenwriter.writer import Screenwriter


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
    state = store.session("screenwriter-live-probe")
    sw = Screenwriter(llm=caller)

    clay = build_writing_materials(
        compose_meta={
            "persona_brief": "安静、喜欢整理标本的角色；说话克制，观察力强。",
            "dynamic_memory_ids": ["mem-thistle", "mem-lamp", "mem-leaf"],
            "dynamic_memory_texts": [
                "昨夜在标本台整理蓟花标本",
                "帐篷角落有一盏暖色台灯",
                "桌上散着几片带横纹的干叶",
            ],
            "dynamic_share_texts": [
                "想聊聊干叶上的横纹像不像潮水退去后的沙滩",
            ],
        },
        fate_speak_desire=62,
        fate_tendency="愿意接话",
        presence_mood="平静",
        presence_brief="在标本台前整理",
        dialogue_history="（新会话，尚无往返）",
        recent_turns=(),
        silence_log=(),
        last_user_text="",
        last_user_speak_at=0.0,
        last_agent_speak_at=0.0,
        scene_seeds=("蓟花", "标本台", "台灯", "干叶", "压纸", "镊子", "帐篷", "暖光", "花萼", "吸水纸"),
    )
    materials = clay.as_dict()

    print("[screenwriter] init_presence via live LLM …")
    out = sw.init_presence(
        state,
        session_id="screenwriter-live-probe",
        user_text="",
        turn_index=0,
        materials=materials,
        speak_desire=62,
    )
    payload = out.payload if hasattr(out, "payload") else dict(out)

    # 模拟导演消费 2 个 unit，再触发活队列不足时的补仓
    consumed = []
    for _ in range(2):
        prev = state.plot_arc.active_unit()
        if prev is None:
            break
        consumed.append(prev.intent)
        sw.confirm_interaction_unit_complete(
            state,
            poll_seq=1,
            reason="live_probe_consume",
        )

    state.poll_seq = 2
    print(
        f"[screenwriter] after consume live={state.plot_arc.live_unit_count()} "
        f"history={len(state.plot_arc.unit_history)} → tick refill …"
    )
    refill_out = sw.tick_on_poll(
        state,
        session_id="screenwriter-live-probe",
        turn_index=1,
        materials=materials,
        dialogue_history="用户还没开口；角色继续手头标本。",
        force=False,
        async_write=False,
        speak_desire=62,
    )

    report = {
        "llm_model": cfg.model,
        "used_fallback_init": bool(getattr(out, "used_fallback", False)),
        "reason_init": getattr(out, "reason", "") or payload.get("reason"),
        "writing_materials_preview": clay.render_for_screenwriter()[:1200],
        "narrative_opening": state.director_cache.get("narrative_opening"),
        "scene_seeds": state.director_cache.get("scene_seeds"),
        "consumed_units": consumed,
        "plot_arc": state.plot_arc.snapshot() if state.plot_arc.ready else None,
        "plot_flow": state.plot_flow.snapshot() if state.plot_flow.ready else None,
        "material_schedule": {
            "inject_memory": state.plot_flow.inject_memory,
            "memory_unit_ids": list(state.plot_flow.memory_unit_ids),
            "inject_share": state.plot_flow.inject_share,
            "share_indices": list(state.plot_flow.share_indices),
            "material_reason": state.plot_flow.material_reason,
        },
        "presence_card": {
            "mood": state.presence_card.mood,
            "brief": state.presence_card.brief,
        },
        "narrative_card": {
            "user_activity": state.narrative_card.user_activity,
            "interaction_mode": state.narrative_card.interaction_mode,
        },
        "refill": {
            "ran": refill_out is not None,
            "reason": getattr(refill_out, "reason", None) if refill_out else None,
            "live_after": state.plot_arc.live_unit_count(),
            "history_after": len(state.plot_arc.unit_history),
        },
        "notes": [n for n in state.notes if "screenwriter" in str(n)],
    }

    out_path = Path(__file__).with_name("screenwriter_live_output.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[screenwriter] wrote {out_path}")
    print("--- opening (user) ---")
    print(report["narrative_opening"] or "(empty)")
    print("--- plot_arc.summary (role) ---")
    arc = report["plot_arc"] or {}
    print(arc.get("summary") or "(empty)")
    print("--- live units ---")
    for u in arc.get("units") or []:
        print(f"  - [{u.get('status')}] {u.get('intent')}")
    print("--- history ---")
    for h in arc.get("unit_history") or []:
        print(f"  - [done] {h.get('intent')}")
    print("--- material schedule ---")
    print(report["material_schedule"])
    print("--- focus_now ---")
    flow = report["plot_flow"] or {}
    print(flow.get("focus_now") or "(empty)")
    print("--- refill ---")
    print(report["refill"])


if __name__ == "__main__":
    main()
