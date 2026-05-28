from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.profile.store import ProfileStore
from agent.soul.service import SoulService
from agent.soul.testing.turing import (
    SoulTuringHarness,
    TuringAgentJudge,
    TuringVerdictKind,
    parse_turing_verdict_line,
)
from agent.soul.testing.turing.stubs import (
    AgentLikeSpeakLLM,
    FaqSpeakLLM,
    ScriptedExternalJudge,
)
from config.agent.persona_config import PersonaConfig
from config.soul.config import SoulConfig
from config.soul.memory.infra_config import SoulMemoryInfraConfig
from infra.memory import MemoryInfraService


@pytest.fixture
def disabled_memory_infra():
    return MemoryInfraService(
        cfg=SoulMemoryInfraConfig(enabled=False),
        embedding=None,
        vectors=None,
    )


@pytest.fixture
def turing_persona_cfg(soul_temp_dir):
    persona_dir = os.path.join(soul_temp_dir, "persona")
    store = ProfileStore(persona_dir)
    store.save_profile(
        PersonaProfile(
            name="莉奈娅",
            background_facts=["挪德卡莱的博物学家"],
            core_traits=["好奇", "热情"],
        )
    )
    return PersonaConfig(
        enabled=True,
        persona_dir=persona_dir,
        evolution_enabled=False,
    )


@pytest.fixture
def soul_service_agentlike(soul_temp_dir, turing_persona_cfg, disabled_memory_infra):
    svc = SoulService(
        life_dir=os.path.join(soul_temp_dir, "life"),
        persona_cfg=turing_persona_cfg,
        mysql_client=MagicMock(),
        primary_llm=AgentLikeSpeakLLM(),
        cfg=SoulConfig(),
        memory_infra=disabled_memory_infra,
    )
    svc.start()
    yield svc
    if svc.state == "running":
        svc.stop()


@pytest.fixture
def soul_service_faq(soul_temp_dir, turing_persona_cfg, disabled_memory_infra):
    svc = SoulService(
        life_dir=os.path.join(soul_temp_dir, "life"),
        persona_cfg=turing_persona_cfg,
        mysql_client=MagicMock(),
        primary_llm=FaqSpeakLLM(),
        cfg=SoulConfig(),
        memory_infra=disabled_memory_infra,
    )
    svc.start()
    yield svc
    if svc.state == "running":
        svc.stop()


def test_parse_turing_verdict_line():
    head, reason = parse_turing_verdict_line("AGENT\nreason: 有主体性")
    assert head == "AGENT"
    assert "主体" in reason

    head2, _ = parse_turing_verdict_line("NOT_AGENT\nreason: 模板客服")
    assert head2 == "NOT_AGENT"


def test_scripted_judge_control_is_not_agent():
    judge = TuringAgentJudge(ScriptedExternalJudge())
    transcript = SoulTuringHarness.control_faq_transcript()
    verdict = judge.judge(transcript)
    assert verdict.kind == TuringVerdictKind.not_agent
    assert not verdict.is_agent


def test_soul_turing_harness_agentlike_dialogue(soul_service_agentlike):
    harness = SoulTuringHarness(
        soul_service_agentlike,
        session_id="turing-agent",
        judge=ScriptedExternalJudge(),
    )
    transcript, verdict = harness.run_probe(
        [
            "你好，你是谁？",
            "我对你提到的那个年轻酒保有点感兴趣，你知道他的名字么",
        ]
    )

    assert len(transcript.turns) == 2
    assert transcript.persona_name == "莉奈娅"
    assert transcript.turns[0].thought
    assert transcript.turns[0].agent
    assert transcript.turns[1].agent
    assert "酒保" in transcript.turns[1].agent or "小辽" in transcript.turns[1].agent

    assert verdict.kind == TuringVerdictKind.agent
    assert verdict.is_agent


def test_soul_turing_harness_faq_dialogue_judged_not_agent(soul_service_faq):
    harness = SoulTuringHarness(
        soul_service_faq,
        session_id="turing-faq",
        judge=ScriptedExternalJudge(),
    )
    transcript, verdict = harness.run_probe(
        [
            "酒保叫什么名字？",
            "你记得我上次问什么吗？",
        ]
    )

    assert len(transcript.turns) == 2
    assert "Jack" in transcript.turns[0].agent
    assert verdict.kind == TuringVerdictKind.not_agent


def test_transcript_render_marks_control_group():
    ctrl = SoulTuringHarness.control_faq_transcript()
    rendered = ctrl.render_for_judge()
    assert "【对照组" in rendered
    assert "模板客服" in rendered
