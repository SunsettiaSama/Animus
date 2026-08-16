#!/usr/bin/env python3
"""导演剧情推进 live 测：poll1 起势 → 注入交互落实证据 → poll2 应消费并进入下一卡。"""

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


def _preview(obj: Any, *, limit: int = 1000) -> str:
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
        raise SystemExit("missing api_key/model")
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


def _build_service(llm):
    from agent.soul.presence.share_desire import ShareDesire
    from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
    from agent.soul.speak.io.outbound.unit import SpeakAnswer
    from agent.soul.speak.llm.director_engine import SpeakDirectorLLMEngine
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance import (
        SpeakContextDistiller,
    )
    from agent.soul.speak.service import SpeakService
    from agent.soul.speak.session import SpeakTurnChunk, resolve_subjective

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
    persona.get_persona_snapshot.return_value = {
        "profile": {"name": "莉奈娅", "core_traits": ["好奇"], "built": True, "built_at": "smoke"},
        "self_concept": {"narrative": "你在标本桌前做事。", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "plot-progress|",
            "distilled_at": "2026-08-16T00:00:00+00:00",
            "slices": {
                "general": "博物学家莉奈娅，短句，自然。",
                "dialogue": "远程文字往来。",
                "story": "标本桌。",
                "reasoning": "先做完手头再开口。",
                "memory_anchor": "标本、压花板。",
            },
        },
    }
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "专注"
    snap.state.somatic.render.return_value = "指尖有触感"
    snap.state.cognition.render.return_value = "在核对手头步骤"
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
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
        typing_idle_ms=50,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
    )


def _active_unit(state):
    if not state.plot_arc.ready:
        return None
    return state.plot_arc.active_unit()


def _seed_fulfillment_evidence(service, sid: str, *, intent: str, unit_id: str) -> str:
    """注入「角色已落实当前剧情意图」的交互记录，供下一拍 poll 判断。"""
    state = service._state_store.session(sid)
    spoken = (
        f"<body action>我已经把这一步做完了：{intent}。"
        f"现场能核对到结果，当前步骤可以收束。</body action>"
        f"<speak>嗯，这一步我做完了——{intent}，可以往下走了。</speak>"
    )
    state.last_agent_speak_at = time.time()
    state.last_user_speak_at = time.time() - 8.0
    state.last_real_user_text = "你先把手头那步做完，做完跟我说一声。"
    state.director_cache["agent_delivery_trace"] = [
        {
            "status": "delivered",
            "trigger_id": f"seed-{unit_id}",
            "text": spoken,
        }
    ]
    state.director_cache["delivery_step_ledger"] = [
        {
            "delivery_step_id": f"exec-seed-{unit_id[-6:]}",
            "origin": "director",
            "trigger_id": f"seed-{unit_id}",
            "plot_unit_ids": [unit_id],
            "script_text": intent,
            "answer_fingerprint": spoken[:120],
            "turn_index": 1,
            "chose_silence": False,
        }
    ]
    # 让 snapshot 对白里也能看见交互（绕过空 context distill）
    port = service._snapshot_builder._port
    original = port.dialogue_snapshot

    def _dialogue_snapshot(session_id: str, *, user_text: str = ""):
        from agent.soul.speak.responders.request_driven.orchestrator.state.core.types import (
            DialogueSnapshot,
        )

        base = original(session_id, user_text=user_text)
        return DialogueSnapshot(
            user_text=user_text or base.user_text,
            context_distill=base.context_distill,
            working_memory=(
                f"user: 你先把手头那步做完，做完跟我说一声。\n"
                f"agent: 嗯，这一步我做完了——{intent}，可以往下走了。"
            ),
            recent_turns=(
                "user: 你先把手头那步做完，做完跟我说一声。",
                f"agent: 嗯，这一步我做完了——{intent}，可以往下走了。",
            ),
        )

    port.dialogue_snapshot = _dialogue_snapshot  # type: ignore[method-assign]
    return spoken


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="director-plot-progress-live")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.3)
    args = parser.parse_args()

    _sep("load live LLM")
    llm = _load_llm(args)
    service = _build_service(llm)
    coord = service._director_coordinator
    assert coord is not None
    sid = args.session_id.strip()
    service.session_manager.open(sid, trigger="user_message")

    _sep("poll#1 · 起势（应 incomplete）")
    t0 = time.perf_counter()
    poll1 = coord.on_poll_tick(sid, trigger="idle")
    print(f"latency_ms={int((time.perf_counter() - t0) * 1000)}")
    state = service._state_store.session(sid)
    u1 = _active_unit(state)
    if u1 is None:
        print(_preview(poll1, limit=1200))
        raise SystemExit("poll#1 未产生 active plot unit")
    check1 = dict(state.director_cache.get("plot_progress_check") or {})
    print(f"active_before id={u1.unit_id} intent={u1.intent}")
    print(f"plot_progress_check#1=\n{_preview(check1, limit=600)}")
    live_units = [
        {"id": u.unit_id, "status": u.status, "intent": u.intent}
        for u in state.plot_arc.units
    ]
    print(f"plot_arc.units=\n{_preview(live_units, limit=800)}")

    _sep("seed · 注入「当前意图已落实」的用户↔角色交互记录")
    spoken = _seed_fulfillment_evidence(
        service,
        sid,
        intent=u1.intent,
        unit_id=u1.unit_id,
    )
    print(f"seeded_agent_speak_preview={spoken[:180]}…")

    _sep("poll#2 · 应判定消费完毕并进入下一卡")
    t0 = time.perf_counter()
    poll2 = coord.on_poll_tick(sid, trigger="idle")
    print(f"latency_ms={int((time.perf_counter() - t0) * 1000)}")
    state = service._state_store.session(sid)
    check2 = dict(state.director_cache.get("plot_progress_check") or {})
    u2 = _active_unit(state)
    print(f"plot_progress_check#2=\n{_preview(check2, limit=800)}")
    print(
        f"active_after id={(u2.unit_id if u2 else '∅')} "
        f"intent={(u2.intent if u2 else '∅')}"
    )
    print(
        f"plot_arc.units=\n{_preview([{'id': u.unit_id, 'status': u.status, 'intent': u.intent} for u in state.plot_arc.units], limit=800)}"
    )
    schedule_payload = (
        (state.director_cache.get("rhythm_schedule") or {}).get("payload")
        if isinstance(state.director_cache.get("rhythm_schedule"), dict)
        else {}
    )
    print(
        f"rhythm unit_complete="
        f"{schedule_payload.get('interaction_unit_complete') if isinstance(schedule_payload, dict) else None} "
        f"reason={_preview((schedule_payload or {}).get('unit_complete_reason') if isinstance(schedule_payload, dict) else None, limit=300)}"
    )

    done = bool(check2.get("interaction_unit_complete"))
    active_changed = u2 is None or u2.unit_id != u1.unit_id
    old = next((u for u in state.plot_arc.units if u.unit_id == u1.unit_id), None)
    # 消费后旧卡可能仍在队列标 done，或已归档进 unit_history / 移出活队列
    hist_ids = {
        str(getattr(h, "unit_id", "") or (h.get("unit_id") if isinstance(h, dict) else "") or "")
        for h in list(getattr(state.plot_arc, "unit_history", None) or [])
    }
    old_consumed = (old is None) or (old.status == "done") or (u1.unit_id in hist_ids)

    _sep("verdict")
    print(f"complete_flag={done}")
    print(f"old_unit_consumed={old_consumed} (in_live={old is not None}, status={(old.status if old else '∅')})")
    print(f"active_changed={active_changed}")
    ok = done and old_consumed and active_changed
    verdict_path = ROOT / ".react" / "director_plot_progress_verdict.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict = {
        "ok": ok,
        "complete_flag": done,
        "old_unit_consumed": old_consumed,
        "active_changed": active_changed,
        "active_before": {"id": u1.unit_id, "intent": u1.intent},
        "active_after": (
            {"id": u2.unit_id, "intent": u2.intent} if u2 is not None else None
        ),
        "check1": check1,
        "check2": check2,
    }
    verdict_path.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _sep("verdict")
    print(f"complete_flag={done}")
    print(f"old_unit_consumed={old_consumed} (in_live={old is not None}, status={(old.status if old else '∅')})")
    print(f"active_changed={active_changed}")
    print(f"verdict_json={verdict_path}")
    if ok:
        print("PASS · 导演根据交互记录消费了当前剧情卡并推进")
        return 0
    print("FAIL · 导演未能完成剧情卡推进")
    print(_preview(poll2, limit=1200))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
