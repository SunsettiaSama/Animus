"""Orchestrator 预组装 → stitch system → API 冒烟。

与 test_speak_multi_turn_smoke 不同：不走 SpeakService.run_turn 全链路，
而是显式复现 prepare → finalize → finish_turn_bundle → build_turn_system，
再用 SpeakLLMEngine 调主对话 API，校验回复是否符合标签协议与对白预期。

默认 mock（无需网络）：
  pytest src/test/soul/speak/test_speak_compose_prompt_api_smoke.py -v -s

接真实 API（需 -s 才能在控制台看到 LLM 原文与 speak）：
  pytest src/test/soul/speak/test_speak_compose_prompt_api_smoke.py -v -s --run-speak-live \\
    --speak-base-url https://api.deepseek.com/v1 --speak-api-key sk-... --speak-model deepseek-chat
"""
from __future__ import annotations

import json
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
from agent.soul.speak.pipelines.request_driven.orchestrator import (
    SpeakContextDistiller,
    SpeakOrchestrator,
    SpeakPromptBundle,
    SpeakReplyStyle,
    build_turn_system,
    resolve_llm_user_text,
)
from agent.soul.speak.pipelines.request_driven.orchestrator.frame import PreparedComposeFrame
from agent.soul.speak.pipelines.request_driven.orchestrator.session import RegistrySessionComposePort
from agent.soul.speak.session import SpeakSessionService
from agent.soul.speak.session.lifecycle import SpeakSessionRegistry
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

_TAG_LEAK = re.compile(r"\[(?:/?)(?:think|speak|action|state|recall|anchor|observe)\b", re.I)

SMOKE_USER = "你好，我想确认一下预组装的 system 里有没有你的人设锚点和对话引导？"

_PERSONA_NARRATIVE = (
    "你是莉奈娅，边境探险队的同行者与记录者；你说话不急，习惯先听清对方再开口，"
    "语气平稳、偏亲近，关键处才稍微加重。"
)

_GUIDANCE_PLAN_JSON = json.dumps(
    {
        "narrative": (
            "用户带着验证预组装提示词的意图来试探。"
            "你保持莉奈娅那种先听清、再开口的节奏，"
            "用短句确认 system 里确实有人设与引导，不要堆术语清单。"
        ),
        "emit_share_index": None,
        "emit_recall_index": None,
    },
    ensure_ascii=False,
)

_MAIN_REPLY_MOCK = (
    "[think]用户在确认预组装 system 是否含人设与引导，简短回应即可。[/think]"
    "[speak]有的，我这边能看到自叙和对话引导；你照常聊就行。[/speak]"
    "[state:finish]"
)


@dataclass(frozen=True)
class ComposePromptAssembly:
    system: str
    user: str
    bundle: SpeakPromptBundle
    compose_path: str


def _msg_text(message: Any) -> str:
    content = getattr(message, "content", message)
    return str(content or "")


class _ComposeRouteLLM:
    """按 system 路由：persona 蒸馏 / guidance 规划 / 主对话。"""

    def __init__(self, *, main_reply: str = _MAIN_REPLY_MOCK) -> None:
        self._main_reply = main_reply

    def generate_messages(self, messages: list[Any]) -> str:
        system = _msg_text(messages[0]) if messages else ""
        if "对话引导撰写者" in system:
            return _GUIDANCE_PLAN_JSON
        if "会话上下文压缩器" in system:
            return "用户从寒暄切入，想确认预组装提示词是否含人设与引导。"
        if "角色导演" in system:
            return _PERSONA_NARRATIVE
        return self._main_reply

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


def _build_compose_stack(
    llm: Any,
) -> tuple[SpeakOrchestrator, SpeakLLMEngine, SpeakSessionService, SpeakSessionRegistry]:
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="莉奈娅")
    presence = MagicMock()
    presence.snapshot.return_value = _mock_presence_snap()

    engine = SpeakLLMEngine(llm)
    distiller = SpeakContextDistiller(
        llm_engine=engine,
        chunk_size=2,
        submit=lambda task: task(),
    )
    orchestrator = SpeakOrchestrator(
        persona,
        presence,
        context_distiller=distiller,
        guidance_llm=engine,
    )
    registry = SpeakSessionRegistry()
    orchestrator.bind_session_port(RegistrySessionComposePort(registry))
    session_service = SpeakSessionService(registry=registry)
    return orchestrator, engine, session_service, registry


def assemble_turn_prompt(
    orchestrator: SpeakOrchestrator,
    session_service: SpeakSessionService,
    *,
    session_id: str,
    user_text: str,
    frame: PreparedComposeFrame | None = None,
    reply_style: SpeakReplyStyle | None = None,
) -> ComposePromptAssembly:
    """复现 service._compose_bundle 的组装段（不含 run_turn 记账/流式）。"""
    style = reply_style or SpeakReplyStyle()
    registry = session_service.registry
    session_service.open(session_id)
    record = registry.get(session_id)

    if frame is None:
        frame = orchestrator.prepare(
            session_id,
            mode="inbound",
            reply_style=style,
            generation=record.generation,
        )
        compose_path = "sync_prepare"
    else:
        compose_path = "prefetch_frame"

    bundle = orchestrator.finalize(frame, user_text, session_id=session_id)
    bundle.meta["compose_source"] = compose_path

    turn_index = registry.current_turn_index(session_id)
    director = orchestrator.compose_director
    plan = director.load_plan(session_id, turn_index)
    if plan is None:
        plan = director.bootstrap_plan(
            session_id,
            target_turn_index=turn_index,
            user_text=user_text,
            generation=record.generation,
            bundle_meta=orchestrator.compose_cache(session_id).meta_snapshot(),
            mode="inbound",
        )
        director.save_plan(plan)
    ctx = orchestrator.pipeline_context(
        session_id=session_id,
        turn_index=turn_index,
        user_text=user_text,
        generation=record.generation,
        mode="inbound",
        social=session_service.social,
    )
    finished = director.finish_turn(plan, bundle, ctx)
    system = build_turn_system(finished)
    user = resolve_llm_user_text(finished, user_text)
    return ComposePromptAssembly(
        system=system,
        user=user,
        bundle=finished,
        compose_path=compose_path,
    )


def assemble_turn_prompt_from_prefetch(
    orchestrator: SpeakOrchestrator,
    session_service: SpeakSessionService,
    *,
    session_id: str,
    user_text: str,
    reply_style: SpeakReplyStyle | None = None,
) -> ComposePromptAssembly:
    """模拟 SpeakComposeRunner 缓存命中：先 prepare 帧，再在用户入站时 finalize。"""
    style = reply_style or SpeakReplyStyle()
    registry = session_service.registry
    session_service.open(session_id)
    record = registry.get(session_id)
    frame = orchestrator.prepare(
        session_id,
        mode="inbound",
        reply_style=style,
        generation=record.generation,
    )
    return assemble_turn_prompt(
        orchestrator,
        session_service,
        session_id=session_id,
        user_text=user_text,
        frame=frame,
        reply_style=style,
    )


def assert_assembled_system(system: str) -> None:
    assert "你是生活在虚拟世界中的真实个体" in system
    assert "莉奈娅" in system or "探险" in system
    assert "用户" in system and "你" in system
    assert "回复时请用成对标签" in system
    assert "【编排态" not in system
    assert "【对话引导 ·" not in system


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
            max_tokens=1024,
            temperature=0.7,
        )
    )


def assert_api_reply(raw: str, *, user_text: str) -> str:
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "finish", parsed.to_dict()
    speak = (parsed.speak or raw).strip()
    assert speak, "speak 对白不能为空"
    assert _TAG_LEAK.search(speak) is None, f"标签泄漏: {speak!r}"
    assert "【输出格式】" not in speak
    assert user_text.strip()
    return speak


def test_compose_prompt_api_smoke_mock_sync_path() -> None:
    orchestrator, engine, session_service, _ = _build_compose_stack(_ComposeRouteLLM())
    assembly = assemble_turn_prompt(
        orchestrator,
        session_service,
        session_id="compose-api-mock",
        user_text=SMOKE_USER,
    )

    assert_assembled_system(assembly.system)
    assert assembly.compose_path == "sync_prepare"
    assert isinstance(assembly.bundle.meta.get("turn_compose_assembly"), dict)

    result = engine.generate(assembly.user, system=assembly.system)
    speak = assert_api_reply(result.text, user_text=SMOKE_USER)
    assert any(token in speak for token in ("自叙", "引导", "人设", "有的", "能看到"))


def test_compose_prompt_api_smoke_mock_prefetch_path() -> None:
    orchestrator, engine, session_service, _ = _build_compose_stack(_ComposeRouteLLM())
    assembly = assemble_turn_prompt_from_prefetch(
        orchestrator,
        session_service,
        session_id="compose-api-prefetch",
        user_text=SMOKE_USER,
    )

    assert_assembled_system(assembly.system)
    assert assembly.compose_path == "prefetch_frame"
    assert assembly.bundle.meta.get("compose_source") == "prefetch_frame"

    result = engine.generate(assembly.user, system=assembly.system)
    speak = assert_api_reply(result.text, user_text=SMOKE_USER)
    assert "有的" in speak or "自叙" in speak


@pytest.mark.network
def test_compose_prompt_api_smoke_live(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--run-speak-live"):
        pytest.skip("加 --run-speak-live 以接真实 LLM 试跑")

    llm = _resolve_live_llm(request)
    orchestrator, engine, session_service, _ = _build_compose_stack(llm)
    assembly = assemble_turn_prompt(
        orchestrator,
        session_service,
        session_id="compose-api-live",
        user_text=SMOKE_USER,
    )

    assert_assembled_system(assembly.system)
    print("\n=== compose→API 冒烟 · 组装摘要 ===")
    print(f"compose_path={assembly.compose_path} system_chars={len(assembly.system)}")
    print(f"user_prompt={assembly.user!r}")
    print("\n--- system（前 1200 字）---")
    print(assembly.system[:1200])
    if len(assembly.system) > 1200:
        print("...(system truncated)")

    result = engine.generate(assembly.user, system=assembly.system)
    parsed = parse_agent_output(result.text)
    speak = assert_api_reply(result.text, user_text=SMOKE_USER)

    print("\n=== compose→API 冒烟 · LLM 原始回复 ===")
    print(result.text)
    print("\n--- 解析结果 ---")
    print(f"session_state={parsed.session_state!r}")
    if parsed.thought.strip():
        print(f"think: {parsed.thought}")
    print(f"speak: {speak}")
    if parsed.actions:
        print(f"actions: {parsed.actions}")
    print(f"\n用户: {SMOKE_USER}")

    assert any(token in speak for token in ("你好", "在", "有", "可以", "能", "看到", "人设", "引导", "自叙")), (
        f"回复应回应预组装/人设话题，实际: {speak!r}"
    )
    assert len(speak) <= 400, f"live 冒烟回复过长: {len(speak)} chars"
