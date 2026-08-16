#!/usr/bin/env python3
"""落地诊断：无用户接话时，导演为何连推三拍、剧情卡不翻。"""

from __future__ import annotations

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


def _clip(text: Any, n: int = 220) -> str:
    body = str(text or "").replace("\n", " ")
    return body if len(body) <= n else body[: n - 1] + "…"


def _load_llm():
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM

    cfg_path = ROOT / "config" / "llm_core" / "config.yaml"
    cfg = LLMConfig.from_yaml(str(cfg_path)) if cfg_path.is_file() else LLMConfig()
    api_key = (
        os.environ.get("SPEAK_SMOKE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or cfg.api_key
        or ""
    ).strip()
    model = (os.environ.get("SPEAK_SMOKE_MODEL") or cfg.model or "").strip()
    base_url = (
        os.environ.get("SPEAK_SMOKE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or cfg.base_url
        or ""
    ).strip()
    if not api_key or not model:
        raise SystemExit("missing api_key/model")
    print(f"model={model}")
    return OpenAILLM(
        LLMConfig(
            backend="openai",
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            max_tokens=1024,
            temperature=0.4,
        )
    )


def _build_service(llm):
    from agent.soul.presence.share_desire import ShareDesire
    from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
    from agent.soul.speak.io.outbound.unit import SpeakAnswer
    from agent.soul.speak.llm.director_engine import SpeakDirectorLLMEngine
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance import (
        SpeakContextDistiller,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
        plot_progress_fingerprint,
    )
    from agent.soul.speak.service import SpeakService
    from agent.soul.speak.session import SpeakTurnChunk, resolve_subjective

    class _LifeStub:
        def touch_dialogue(self, session_id: str) -> None:
            del session_id

        def emit_dialogue_turn(self, chunk: SpeakTurnChunk) -> None:
            del chunk

        def record_turn_exchange(self, chunk: SpeakTurnChunk) -> SpeakExchange:
            return SpeakExchange(
                session_id=chunk.session_id,
                question=SpeakQuestion(text=chunk.user_text),
                answer=SpeakAnswer(text=chunk.agent_text),
                subjective=resolve_subjective(chunk),
                feeling=chunk.feeling,
            )

    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {
        "profile": {"name": "莉", "core_traits": ["好奇"], "built": True, "built_at": "live"},
        "self_concept": {"narrative": "营地外缘泥径，雨后斜光。", "beliefs": []},
        "attention_keywords": ["泥径", "蓟花"],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "silent-loop|",
            "distilled_at": "2026-08-16T00:00:00+00:00",
            "slices": {
                "general": "短句，带一点观察。",
                "dialogue": "通过通信设备文字往来。",
                "story": "雨后泥径，蓟花冠上有水珠。",
                "reasoning": "先看眼前再开口。",
                "memory_anchor": "泥径、爪印、蓟花。",
            },
        },
    }
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "平静"
    snap.state.somatic.render.return_value = "指尖有泥"
    snap.state.cognition.render.return_value = "在看泥径"
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = "雨后斜光"
    snap.state.expectation.toward_user = 0.3
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.2
    presence.snapshot.return_value = snap

    engine = SpeakLLMEngine(llm)
    return SpeakService(
        persona=persona,
        presence=presence,
        llm_engine=engine,
        director_llm_engine=SpeakDirectorLLMEngine(llm),
        context_distiller=SpeakContextDistiller(
            llm_engine=engine,
            chunk_size=2,
            submit=lambda task: task(),
        ),
        life_outbound=_LifeStub(),
        life_lifecycle=None,
        context_distill_chunk_size=2,
        typing_idle_ms=50,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
    ), plot_progress_fingerprint


def _fp_parts(state) -> dict[str, Any]:
    active = state.plot_arc.active_unit() if state.plot_arc.ready else None
    flow = state.plot_flow
    return {
        "unit_id": str(getattr(active, "unit_id", "") or ""),
        "status": str(getattr(active, "status", "") or ""),
        "polls_consumed": int(getattr(active, "polls_consumed", 0) or 0),
        "flow_version": int(getattr(flow, "version", 0) or 0),
        "flow_poll_seq": int(getattr(flow, "poll_seq", 0) or 0),
        "beats": len(list(getattr(flow, "beats", None) or [])),
        "focus_now": str(getattr(flow, "focus_now", "") or "")[:48],
        "next_push": str(getattr(flow, "next_push", "") or "")[:48],
        "state_poll_seq": int(getattr(state, "poll_seq", 0) or 0),
    }


def _dump_beat(state, plot_progress_fingerprint, label: str) -> dict[str, Any]:
    from agent.soul.speak.responders.request_driven.character.interaction import (
        export_interaction_record,
    )

    arc = state.plot_arc
    active = arc.active_unit() if arc.ready else None
    check = dict(state.director_cache.get("plot_progress_check") or {})
    fp = plot_progress_fingerprint(state.plot_arc, state.plot_flow)
    parts = _fp_parts(state)
    units = []
    for entry in list(state.character_rhythm_schedule.executable_units or []):
        units.append(
            {
                "id": entry.unit_id,
                "status": entry.status,
                "plot": list(entry.plot_unit_ids),
                "focus": entry.focus,
                "intent": entry.intent,
                "direction": entry.direction,
                "exit": entry.exit,
                "script": entry.script_text,
                "open_at": entry.open_at,
            }
        )
    rec = export_interaction_record(state)
    private = getattr(state.character_rhythm_schedule, "private", None)
    rhythm = state.director_cache.get("rhythm_schedule") or {}
    payload = rhythm.get("payload") if isinstance(rhythm, dict) else {}
    hist = list(state.character_rhythm_schedule.consumption_history or [])
    would_block = False
    due = [
        e
        for e in state.character_rhythm_schedule.executable_units
        if e.status in ("pending", "reserved")
    ]
    if due:
        would_block = state.character_rhythm_schedule.blocks_repeat_without_plot_progress(
            due[0].plot_unit_ids,
            plot_fingerprint=fp,
        )
    row = {
        "label": label,
        "active_plot_id": getattr(active, "unit_id", "") if active else "",
        "active_plot_intent": getattr(active, "intent", "") if active else "",
        "plot_index": getattr(arc, "current_index", None) if arc.ready else None,
        "complete": check.get("interaction_unit_complete"),
        "complete_reason": check.get("unit_complete_reason"),
        "fingerprint": fp,
        "fp_parts": parts,
        "handoff": bool(state.pending_character_handoff),
        "rhythm_action": (payload or {}).get("action") if isinstance(payload, dict) else None,
        "would_block_repeat": would_block,
        "consumption_n": len(hist),
        "exec_units": units,
        "last_agent": rec.last_agent_text[:180],
        "private": {
            "thinking": getattr(private, "thinking", "") if private else "",
            "noticing": getattr(private, "noticing", "") if private else "",
            "wanting": getattr(private, "wanting", "") if private else "",
        },
        "notes": [
            n
            for n in state.notes[-16:]
            if any(
                k in str(n)
                for k in (
                    "rhythm",
                    "plot",
                    "handoff",
                    "blocked",
                    "skip_handoff",
                    "delivery_step",
                )
            )
        ],
    }
    _sep(label)
    print(f"active_plot={row['active_plot_id']}  {row['active_plot_intent']}")
    print(f"complete={row['complete']}  reason={_clip(row['complete_reason'], 220)}")
    print(f"rhythm_action={row['rhythm_action']}  handoff={row['handoff']}")
    print(f"fingerprint={row['fingerprint']}")
    print(f"fp_parts={parts}")
    print(f"would_block_repeat={would_block}  consumption_n={len(hist)}")
    if row["private"]["thinking"] or row["private"]["wanting"]:
        print(f"private.thinking={_clip(row['private']['thinking'], 240)}")
        print(f"private.wanting={_clip(row['private']['wanting'], 240)}")
    for u in units:
        print(
            f"  exec [{u['status']}] {u['id']} plot={u['plot'] or '—'}\n"
            f"    focus={_clip(u['focus'])}\n"
            f"    intent={_clip(u['intent'])}\n"
            f"    direction={_clip(u['direction'])}\n"
            f"    exit={_clip(u['exit'])}"
        )
    return row


def main() -> int:
    from agent.soul.speak.responders.request_driven.character.interaction import (
        note_character_exchange,
    )

    _sep("load")
    llm = _load_llm()
    service, plot_progress_fingerprint = _build_service(llm)
    coord = service._director_coordinator
    if coord is None:
        raise SystemExit("no coordinator")
    sid = "director-silent-loop-live"
    service.session_manager.open(sid, trigger="user_message")
    state = service._state_store.session(sid)

    _sep("screenwriter init (sync)")
    coord.screenwriter.init_presence(
        state,
        session_id=sid,
        user_text="",
        turn_index=0,
        background_agent=False,
        materials={
            "scene_seeds": ["泥径", "蕨叶", "雨后爪印", "赤狐", "蓟花", "林缘"],
        },
    )
    print(f"plot_ready={state.plot_arc.ready} summary={_clip(state.plot_arc.summary, 200)}")
    if state.plot_arc.ready:
        for i, u in enumerate(state.plot_arc.units[:6]):
            print(f"  plot[{i}] {u.status} {u.intent}")

    beats: list[dict[str, Any]] = []
    spoken = [
        "蹲下来拨开蓟叶。雨后爪印还湿着，像刚走过一只赤狐。你说，它是不是也嫌这路滑？",
        "爪印往西去了，和蜂鸟路线错开。你说，这片林子是不是比我们想的热闹？",
        "后爪叠在前爪上，像赶着赴约。你说，它是不是也只是路过，却想再多看一眼？",
    ]

    for i in range(3):
        _sep(f"poll #{i + 1} · 无用户接话")
        t0 = time.perf_counter()
        coord.on_poll_tick(sid, trigger="idle")
        print(f"poll_ms={int((time.perf_counter() - t0) * 1000)}")
        row = _dump_beat(state, plot_progress_fingerprint, f"after poll #{i + 1}")
        # 模拟角色已按当前指令开口（截图那种自说自话），再让导演判断要不要翻卡
        note_character_exchange(state, user_text="", agent_text=spoken[i])
        state.last_agent_speak_at = time.time()
        schedule = state.character_rhythm_schedule
        target = None
        for entry in schedule.executable_units:
            if entry.status in ("pending", "reserved"):
                target = entry
                break
        if target is None:
            for entry in schedule.executable_units:
                if entry.status == "consumed":
                    target = entry
                    break
        fp = plot_progress_fingerprint(state.plot_arc, state.plot_flow)
        if target is not None and target.status in ("pending", "reserved"):
            if target.status == "pending":
                schedule.mark_reserved(target.unit_id)
            schedule.mark_consumed(
                target.unit_id,
                turn_index=i + 1,
                trigger_id=f"silent-loop-{i + 1}",
                plot_fingerprint=fp,
                script_text=target.script_text,
                answer_fingerprint=spoken[i][:120],
            )
        ledger = list(state.director_cache.get("delivery_step_ledger") or [])
        ledger.append(
            {
                "delivery_step_id": target.unit_id if target else f"exec-sim-{i}",
                "origin": "director",
                "plot_unit_ids": list(target.plot_unit_ids) if target else [],
                "answer_fingerprint": spoken[i][:120],
                "turn_index": i + 1,
                "chose_silence": False,
                "plot_fingerprint": fp,
            }
        )
        state.director_cache["delivery_step_ledger"] = ledger
        state.director_cache["character_rhythm_schedule"] = schedule.snapshot()
        row["seeded_speak"] = spoken[i]
        row["consumed_exec"] = target.unit_id if target else ""
        row["consumed_fp"] = fp
        beats.append(row)

    _sep("verdict")
    ids = [b["active_plot_id"] for b in beats]
    completes = [b["complete"] for b in beats]
    fps = [b["fingerprint"] for b in beats]
    print(f"active_plot_ids={ids}")
    print(f"complete_flags={completes}")
    print(f"fingerprint_changed={len(set(fps)) > 1}")
    print(f"plot_advanced={len(set(x for x in ids if x)) > 1}")
    if len(beats) >= 2:
        keys = set()
        for b in beats:
            keys.update((b.get("fp_parts") or {}).keys())
        for key in sorted(keys):
            vals = [(b.get("fp_parts") or {}).get(key) for b in beats]
            if len(set(str(v) for v in vals)) > 1:
                print(f"  fp_part_changed {key}={vals}")
    exits = [u.get("exit") for b in beats for u in b.get("exec_units") or []]
    print(f"exit_count={len(exits)}")
    for ex in exits:
        print(f"  exit={_clip(ex, 160)}")
    out = ROOT / ".react" / "director_silent_loop_verdict.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(beats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
