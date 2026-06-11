"""Speak 多轮对话冒烟：验证 compose → LLM → 记账 链路与输出是否像真人交互。

默认使用脚本化 LLM（无需网络）：
  pytest src/test/soul/speak/test_speak_multi_turn_smoke.py -v -s --noconftest

接真实 LLM 试跑（需 API）：
  pytest src/test/soul/speak/test_speak_multi_turn_smoke.py -v -s --noconftest --run-speak-live \\
    --speak-base-url https://api.deepseek.com/v1 --speak-api-key sk-... --speak-model deepseek-chat

或直接打印对话 transcript：
  python -m test.soul.speak.test_speak_multi_turn_smoke
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

SRC = Path(__file__).resolve().parent.parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.io.outbound.stream import parse_agent_output
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.orchestrator.guidance.context import SpeakContextDistiller
from agent.soul.speak.service import SpeakService, SpeakTurnResult
from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound

_TAG_LEAK = re.compile(r"\[(?:/?)(?:think|speak|action|state|recall|anchor|observe)\b", re.I)
_JSONish = re.compile(r"^\s*[\[{]")


@dataclass(frozen=True)
class SmokeTurn:
    user: str
    scripted_reply: str = ""


MULTI_TURN_SCRIPT: tuple[SmokeTurn, ...] = (
    SmokeTurn(
        user="你好，最近怎么样？",
        scripted_reply=(
            "[think]对方在打招呼，先轻松回应，别太长。[/think]"
            "[action]微微抬眼[/action]"
            "[speak]还行，今天节奏不算紧。你那边呢？[/speak]"
            "[state:finish]"
        ),
    ),
    SmokeTurn(
        user="我在整理 speak 模块的架构文档，想确认多轮对话链路。",
        scripted_reply=(
            "[think]对方在聊 speak 架构，接上一句问候，给一点具体感。[/think]"
            "[speak]speak 这条链路我熟一点：先拼 prompt，再出话，最后记账。"
            "你文档里如果写「编排 → LLM → 流式 → 体验」，方向就对了。[/speak]"
            "[state:finish]"
        ),
    ),
    SmokeTurn(
        user="那工作记忆会在多轮里更新吗？",
        scripted_reply=(
            "[think]第三问，要呼应前面聊过的架构，别像 FAQ。[/think]"
            "[speak]会的。每轮说完会进工作记忆，攒够几轮还会压成一句摘要。"
            "所以你现在连问三轮，我这边上下文是在往前走的。[/speak]"
            "[state:finish]"
        ),
    ),
)

_GUIDANCE_PLAN_JSON = json.dumps(
    {
        "narrative": (
            "用户带着明确问题来聊 speak 架构与多轮记忆。"
            "你保持莉奈娅那种先听清、再开口的节奏，"
            "用短句回应，必要时补一句具体机制，不要堆术语清单。"
        ),
        "emit_share_index": None,
        "emit_recall_index": None,
    },
    ensure_ascii=False,
)

_DISTILL_ONE_LINER = "用户从寒暄切入，开始讨论 speak 架构与多轮工作记忆。"

_STRUCTURED_DISTILL_JSON = json.dumps(
    {
        "summary": "你从寒暄进入 speak 架构讨论，语气平稳。",
        "emotion_label": "专注",
        "mood_span": "接下来你会觉得讨论有条理",
        "linger_days": 1.0,
        "subjective_narrative": "你在帮对方理清 speak 多轮链路。",
        "valence": "positive",
        "salience": 0.5,
        "valence_delta": 0.05,
        "arousal_delta": 0.02,
    },
    ensure_ascii=False,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    existing = {o.dest for o in parser._anonymous.options}

    def _add(name: str, **kwargs: Any) -> None:
        dest = name.lstrip("-").replace("-", "_")
        if dest not in existing:
            parser.addoption(name, **kwargs)

    _add(
        "--run-speak-live",
        action="store_true",
        default=False,
        help="使用真实 LLM 跑 speak 多轮冒烟（需 --speak-base-url / --speak-api-key）",
    )
    _add("--speak-model", default=os.environ.get("SPEAK_SMOKE_MODEL", "deepseek-chat"))
    _add("--speak-base-url", default=os.environ.get("SPEAK_SMOKE_BASE_URL"))
    _add("--speak-api-key", default=os.environ.get("SPEAK_SMOKE_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _msg_text(message: Any) -> str:
    content = getattr(message, "content", message)
    return str(content or "")


def _persona_snapshot() -> dict[str, Any]:
    return {
        "profile": {"name": "莉奈娅", "core_traits": ["calm"], "built": True, "built_at": "test"},
        "self_concept": {"narrative": "I accompany the user.", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "test|",
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "slices": {
                "general": "莉奈娅：冷静、克制",
                "dialogue": (
                    "你是莉奈娅，边境探险队的同行者与记录者。你说话不急，"
                    "习惯先听清对方再开口；语气平稳、偏亲近，少花哨。"
                ),
                "story": "背景待续",
                "reasoning": "先框架后细节",
                "memory_anchor": "你是冷静陪伴者，习惯把对话整理成可回顾的线索。",
            },
        },
    }


_PERSONA_NARRATIVE_LINE = (
    "莉奈娅是边境探险队的记录者，说话不急，习惯先听清对方再开口，"
    "语气平稳、偏亲近，少花哨。"
)


class _ScriptedSpeakLLM:
    """按 system / user 内容分支，模拟主对话、引导规划、上下文蒸馏。"""

    def __init__(self, turns: tuple[SmokeTurn, ...]) -> None:
        self._turns = turns
        self._turn_idx = 0

    def _next_main_reply(self, user: str) -> str:
        for offset in range(len(self._turns)):
            idx = (self._turn_idx + offset) % len(self._turns)
            turn = self._turns[idx]
            if turn.user in user or user.strip() == turn.user.strip():
                self._turn_idx = idx + 1
                return turn.scripted_reply
        fallback = self._turns[min(self._turn_idx, len(self._turns) - 1)]
        self._turn_idx += 1
        return fallback.scripted_reply

    def generate_messages(self, messages: list[Any]) -> str:
        system = _msg_text(messages[0]) if messages else ""
        user = _msg_text(messages[-1]) if messages else ""

        if "对话引导撰写者" in system:
            return _GUIDANCE_PLAN_JSON

        if "会话上下文压缩器" in system:
            return _DISTILL_ONE_LINER

        if "会话体验压缩器" in system:
            return _STRUCTURED_DISTILL_JSON

        if "角色导演" in system:
            return _PERSONA_NARRATIVE_LINE

        return self._next_main_reply(user)

    def stream_generate_messages(self, messages: list[Any]):
        text = self.generate_messages(messages)
        for ch in text:
            yield ch


def _mock_presence_snap() -> MagicMock:
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


def _build_speak_service(*, llm: Any) -> tuple[SpeakService, RecordingSpeakLifeOutbound]:
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = _persona_snapshot()
    presence = MagicMock()
    presence.snapshot.return_value = _mock_presence_snap()

    engine = SpeakLLMEngine(llm)
    distiller = SpeakContextDistiller(
        llm_engine=engine,
        chunk_size=2,
        submit=lambda task: task(),
    )
    life_out = RecordingSpeakLifeOutbound()
    service = SpeakService(
        persona=persona,
        presence=presence,
        llm_engine=engine,
        context_distiller=distiller,
        life_outbound=life_out,
        life_lifecycle=None,
        context_distill_chunk_size=2,
        typing_idle_ms=50,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
    )
    return service, life_out


def assert_human_like_answer(answer: str, *, min_chars: int = 6, max_chars: int = 600) -> None:
    text = answer.strip()
    assert text, "回复不能为空"
    assert len(text) >= min_chars, f"回复过短: {text!r}"
    assert len(text) <= max_chars, f"回复过长 ({len(text)} chars)"
    assert _TAG_LEAK.search(text) is None, f"标签泄漏到 speak: {text!r}"
    assert _JSONish.match(text) is None, f"回复像 JSON 而非对白: {text!r}"
    assert "【输出格式】" not in text


def assert_turn_quality(result: SpeakTurnResult, *, user_text: str) -> None:
    assert result.recorded is True, result.notes
    assert result.output is not None
    assert result.output.session_state == "finish", result.output.to_dict()
    assert result.meta.get("turn_index", 0) >= 1
    assert_human_like_answer(result.answer)
    assert user_text.strip()


def run_multi_turn_dialogue(
    service: SpeakService,
    turns: tuple[SmokeTurn, ...],
    *,
    session_id: str = "smoke-speak",
    stream: bool = False,
) -> list[SpeakTurnResult]:
    results: list[SpeakTurnResult] = []
    for turn in turns:
        result = service.run_turn(session_id, turn.user, stream=stream, record=True)
        assert_turn_quality(result, user_text=turn.user)
        results.append(result)
    return results


def _print_transcript(
    service: SpeakService,
    turns: tuple[SmokeTurn, ...],
    results: list[SpeakTurnResult],
    *,
    life_out: RecordingSpeakLifeOutbound,
) -> None:
    session_id = results[-1].session_id if results else "smoke-speak"
    print("\n=== Speak 多轮冒烟 transcript ===")
    for idx, (turn, result) in enumerate(zip(turns, results), start=1):
        print(f"\n--- 第 {idx} 轮 ---")
        print(f"用户: {turn.user}")
        print(f"Agent: {result.answer}")
        print(f"turn_index={result.meta.get('turn_index')} recorded={result.recorded}")
        if result.output and result.output.thought:
            print(f"(think) {result.output.thought[:80]}")
    wm = service.session_working_memory_block(session_id)
    distill = ""
    if service.context_distiller is not None:
        distill = service.context_distiller.context_distill_block(session_id)
    print(f"\n上下文蒸馏:\n{distill or '(空)'}")
    print(f"\n工作记忆:\n{wm or '(空)'}")
    print(f"\nLife 记账条数: {len(life_out.recorded)}")
    for row in life_out.recorded:
        print(f"  - u={row['user_text'][:24]!r} a={row['agent_text'][:40]!r}")


def test_speak_multi_turn_smoke_mock() -> None:
    service, life_out = _build_speak_service(llm=_ScriptedSpeakLLM(MULTI_TURN_SCRIPT))
    results = run_multi_turn_dialogue(service, MULTI_TURN_SCRIPT, session_id="smoke-speak")

    assert len(life_out.recorded) == len(MULTI_TURN_SCRIPT)
    assert life_out.recorded[0]["user_text"] == MULTI_TURN_SCRIPT[0].user
    assert life_out.recorded[-1]["user_text"] == MULTI_TURN_SCRIPT[-1].user

    wm = service.session_working_memory_block("smoke-speak")
    assert wm.strip(), "多轮后工作记忆应有内容"
    assert any(k in wm for k in ("speak", "架构", "工作记忆", "prompt", "记账"))

    trace = service.session_trace_cache("smoke-speak")
    assert trace["turn_index"] >= len(MULTI_TURN_SCRIPT)

    for result in results:
        assert "compose_source" in result.bundle.meta


def test_speak_multi_turn_smoke_stream_mock() -> None:
    service, life_out = _build_speak_service(llm=_ScriptedSpeakLLM(MULTI_TURN_SCRIPT))
    results = run_multi_turn_dialogue(
        service,
        MULTI_TURN_SCRIPT[:2],
        session_id="smoke-stream",
        stream=True,
    )
    assert all(r.stream_events for r in results)
    speak_events = [e for r in results for e in r.stream_events if e.kind == "speak"]
    assert speak_events, "流式模式应产生 speak 事件"
    assert len(life_out.recorded) == 2


@pytest.mark.network
def test_speak_multi_turn_smoke_live(request: pytest.FixtureRequest) -> None:
    live = os.environ.get("SPEAK_SMOKE_LIVE") == "1"
    if not live:
        live = bool(request.config.getoption("run_speak_live", default=False))
    if not live:
        pytest.skip("加 --run-speak-live 或 SPEAK_SMOKE_LIVE=1 以接真实 LLM 试跑")

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

    llm = OpenAILLM(
        LLMConfig(
            backend="openai",
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_tokens=1024,
            temperature=0.7,
        )
    )
    service, life_out = _build_speak_service(llm=llm)

    live_turns = tuple(SmokeTurn(user=t.user) for t in MULTI_TURN_SCRIPT)
    results = run_multi_turn_dialogue(service, live_turns, session_id="smoke-live", stream=False)

    _print_transcript(service, live_turns, results, life_out=life_out)

    answers = [r.answer for r in results]
    assert len(set(answers)) == len(answers), "三轮回复不应完全雷同"
    assert len(life_out.recorded) == len(live_turns)

    third = results[-1].answer
    assert any(token in third for token in ("记忆", "上下文", "轮", "更新", "摘要")), (
        f"第三轮应回应工作记忆话题，实际: {third!r}"
    )


def main() -> None:
    service, life_out = _build_speak_service(llm=_ScriptedSpeakLLM(MULTI_TURN_SCRIPT))
    results = run_multi_turn_dialogue(service, MULTI_TURN_SCRIPT, session_id="smoke-speak")
    _print_transcript(service, MULTI_TURN_SCRIPT, results, life_out=life_out)


if __name__ == "__main__":
    main()
