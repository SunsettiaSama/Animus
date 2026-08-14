#!/usr/bin/env python3
from __future__ import annotations

import json
import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.io.outbound.unit import SpeakAnswer
from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance import (
    SpeakContextDistiller,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    ReplySegment,
    build_delivery_plan,
)
from agent.soul.speak.service import SpeakService, SpeakTurnResult
from agent.soul.speak.session import (
    SpeakTurnChunk,
    feeling_self_narration,
    resolve_feeling,
    resolve_subjective,
)

TAG_LEAK = re.compile(r"\[(?:/?)(?:think|speak|action|state|recall|anchor|observe)\b", re.I)


@dataclass(frozen=True)
class SmokeTurn:
    user: str
    reply: str


TURNS = (
    SmokeTurn(
        user="你好，最近怎么样？",
        reply=(
            "[think]先轻松回应。[/think]"
            "[speak]还行，今天节奏不算紧。你那边呢？[/speak]"
            "[state:finish]"
        ),
    ),
    SmokeTurn(
        user="我在确认 speak 链路是否能对话。",
        reply=(
            "[think]回应链路验证问题。[/think]"
            "[speak]可以先从脚本跑核心链路：拼 prompt、调用 LLM、解析 speak、再记账。[/speak]"
            "[state:finish]"
        ),
    ),
    SmokeTurn(
        user="那流式输出也能看到吗？",
        reply=(
            "[think]说明 stream event。[/think]"
            "[speak]能看到。流式模式会产生 speak event，最后仍然会落到同一轮结果里。[/speak]"
            "[state:finish]"
        ),
    ),
)

GUIDANCE_PLAN_JSON = json.dumps(
    {
        "narrative": "用户正在验证 speak 对话链路，保持短句回应，说明脚本观察点。",
        "emit_share_index": None,
        "emit_recall_index": None,
    },
    ensure_ascii=False,
)
DISTILL_ONE_LINER = "用户正在确认 speak 核心对话链路和流式输出。"
STRUCTURED_DISTILL_JSON = json.dumps(
    {
        "summary": "你在协助验证 speak 链路。",
        "emotion_label": "专注",
        "mood_span": "接下来你会保持专注排查",
        "linger_days": 1.0,
        "subjective_narrative": "你正在把 speak 链路跑成可复现脚本。",
        "valence": "positive",
        "salience": 0.5,
        "valence_delta": 0.02,
        "arousal_delta": 0.02,
    },
    ensure_ascii=False,
)


class RecordingSpeakLifeOutbound:
    def __init__(self) -> None:
        self.recorded: list[dict[str, Any]] = []

    def touch_dialogue(self, session_id: str) -> None:
        _ = session_id

    def emit_dialogue_turn(self, chunk: SpeakTurnChunk) -> None:
        resolved = resolve_feeling(chunk)
        self.recorded.append(
            {
                "session_id": chunk.session_id,
                "user_text": chunk.user_text,
                "agent_text": chunk.agent_text,
                "salience": resolved.salience,
                "salience_note": feeling_self_narration(chunk.feeling),
                "emotion_label": resolved.emotion_label,
                "valence_delta": resolved.valence_delta,
                "arousal_delta": resolved.arousal_delta,
                "activated_memory_ids": list(chunk.activated_memory_ids),
                "proactive_intent_id": chunk.proactive_intent_id,
            }
        )

    def record_turn_exchange(self, chunk: SpeakTurnChunk) -> SpeakExchange:
        self.emit_dialogue_turn(chunk)
        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
            subjective=resolve_subjective(chunk),
            feeling=chunk.feeling,
        )


class ScriptedSpeakLLM:
    def __init__(self, turns: tuple[SmokeTurn, ...]) -> None:
        self._turns = turns
        self._turn_idx = 0

    def generate_messages(self, messages: list[Any]) -> str:
        system = _message_text(messages[0]) if messages else ""
        user = _message_text(messages[-1]) if messages else ""

        if "对话引导撰写者" in system:
            return GUIDANCE_PLAN_JSON
        if "会话上下文压缩器" in system:
            return DISTILL_ONE_LINER
        if "会话体验压缩器" in system:
            return STRUCTURED_DISTILL_JSON
        if "角色导演" in system:
            return "Lina speaks calmly and keeps replies concrete."

        for offset in range(len(self._turns)):
            idx = (self._turn_idx + offset) % len(self._turns)
            turn = self._turns[idx]
            if turn.user in user or user.strip() == turn.user.strip():
                self._turn_idx = idx + 1
                return turn.reply
        fallback = self._turns[min(self._turn_idx, len(self._turns) - 1)]
        self._turn_idx += 1
        return fallback.reply

    def stream_generate_messages(self, messages: list[Any]):
        for ch in self.generate_messages(messages):
            yield ch


def _message_text(message: Any) -> str:
    return str(getattr(message, "content", message) or "")


def _persona_snapshot() -> dict[str, Any]:
    return {
        "profile": {"name": "Lina", "core_traits": ["calm"], "built": True, "built_at": "smoke"},
        "self_concept": {"narrative": "I accompany the user.", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "smoke|",
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "slices": {
                "general": "Lina is calm and restrained.",
                "dialogue": "You answer gently, with short concrete replies.",
                "story": "No story context.",
                "reasoning": "Listen first, then respond.",
                "memory_anchor": "Keep dialogue clues easy to recall.",
            },
        },
    }


def _presence_snapshot() -> MagicMock:
    snap = MagicMock()
    snap.state.affect.render.return_value = "心情平稳"
    snap.state.somatic.render.return_value = "坐姿放松"
    snap.state.cognition.render.return_value = "思路清楚"
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.3
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.1
    return snap


def _build_service(llm: Any | None = None) -> tuple[SpeakService, RecordingSpeakLifeOutbound]:
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = _persona_snapshot()
    presence = MagicMock()
    presence.snapshot.return_value = _presence_snapshot()

    engine = SpeakLLMEngine(llm or ScriptedSpeakLLM(TURNS))
    distiller = SpeakContextDistiller(
        llm_engine=engine,
        chunk_size=2,
        submit=lambda task: task(),
    )
    life = RecordingSpeakLifeOutbound()
    service = SpeakService(
        persona=persona,
        presence=presence,
        llm_engine=engine,
        context_distiller=distiller,
        life_outbound=life,
        life_lifecycle=None,
        context_distill_chunk_size=2,
        typing_idle_ms=50,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
    )
    return service, life


def _load_live_llm(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM

    cfg_path = ROOT / "config" / "llm_core" / "config.yaml"
    cfg = LLMConfig.from_yaml(str(cfg_path)) if cfg_path.is_file() else LLMConfig()

    base_url = (
        args.base_url
        or os.environ.get("SPEAK_SMOKE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or cfg.base_url
        or ""
    ).strip()
    api_key = (
        args.api_key
        or os.environ.get("SPEAK_SMOKE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or cfg.api_key
        or ""
    ).strip()
    model = (
        args.model
        or os.environ.get("SPEAK_SMOKE_MODEL")
        or cfg.model
        or ""
    ).strip()

    if not api_key:
        raise SystemExit("missing API key: pass --api-key or set SPEAK_SMOKE_API_KEY/OPENAI_API_KEY")
    if not model:
        raise SystemExit("missing model: pass --model or set SPEAK_SMOKE_MODEL or config/llm_core/config.yaml")

    print("=== live LLM ===")
    print(f"model={model}")
    print(f"base_url={base_url or '(provider default)'}")

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


def _force_request_driven_plan(service: SpeakService) -> None:
    plan = build_delivery_plan(
        segments=[
            ReplySegment(
                text="director sample should not be the final answer",
                wait_ms=0,
                wait_reason="smoke",
                continuity="finish",
            ),
        ],
        continuity="finish",
        sample_narration="smoke",
        plan_id="smoke-plan",
        turn_index=1,
    )

    def submit_user_input_sync(
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
        timeout_sec: float = 8.0,
    ):
        _ = user_text, timeout_sec
        state = service._state_store.session(session_id)
        state.speak_gate = "speak"
        state.pending_delivery_plan = plan
        state.delivery_plan = plan
        state.director_cache["turn_delivery"] = {
            "director": "turn_delivery",
            "payload": {"delivery_plan": plan.snapshot()},
            "reason": f"smoke turn {turn_index}",
        }
        return plan

    if service._orchestrator_thread is None:
        raise RuntimeError("request_driven orchestrator thread was not initialized")
    service._orchestrator_thread.submit_user_input_sync = submit_user_input_sync


def _assert_answer(result: SpeakTurnResult) -> None:
    text = result.answer.strip()
    if not text:
        raise RuntimeError("speak returned an empty answer")
    if TAG_LEAK.search(text):
        raise RuntimeError(f"speak leaked control tags: {text!r}")
    if result.output is None or result.output.session_state != "finish":
        raise RuntimeError(f"speak did not finish cleanly: {result.output!r}")
    if not result.recorded:
        raise RuntimeError(f"speak turn was not recorded: {result.notes!r}")


def _print_result(label: str, result: SpeakTurnResult) -> None:
    speak_events = [event for event in result.stream_events if event.kind == "speak"]
    print(f"\n=== {label} ===")
    print(f"user/session: {result.session_id}")
    print(f"answer: {result.answer}")
    print(f"pipeline: {result.meta.get('pipeline')} recorded={result.recorded}")
    print(f"stream_events={len(result.stream_events)} speak_events={len(speak_events)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="use a real OpenAI-compatible API")
    parser.add_argument("--base-url", default="", help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", default="", help="API key; prefer env vars for secrets")
    parser.add_argument("--model", default="", help="model name")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.7)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    llm = _load_live_llm(args) if args.live else None
    service, life = _build_service(llm=llm)

    legacy_results = [
        service.run_turn("smoke-legacy", turn.user, responder="legacy_qa", record=True)
        for turn in TURNS[:2]
    ]
    for result in legacy_results:
        _assert_answer(result)
        _print_result("legacy_qa turn", result)

    _force_request_driven_plan(service)
    request_result = service.run_turn(
        "smoke-request-driven",
        TURNS[2].user,
        responder="request_driven",
        stream=True,
        record=True,
    )
    _assert_answer(request_result)
    _print_result("request_driven stream turn", request_result)

    speak_events = [event for event in request_result.stream_events if event.kind == "speak"]
    if not speak_events:
        raise RuntimeError("request_driven stream did not emit speak events")
    if len(life.recorded) != 3:
        raise RuntimeError(f"expected 3 recorded turns, got {len(life.recorded)}")

    print("\n=== working memory ===")
    print(service.session_working_memory_block("smoke-legacy") or "(empty)")
    print("\nOK: speak smoke passed")


if __name__ == "__main__":
    main()
